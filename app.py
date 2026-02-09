import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Dashboard Flagship Store", layout="wide")

# --- KONEKSI KE GOOGLE DRIVE/SHEETS ---
# Fungsi ini di-cache agar tidak reload data terus menerus setiap klik
@st.cache_data(ttl=600) # Refresh cache setiap 10 menit
def load_data():
    # Setup Credentials dari Streamlit Secrets
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scope
    )
    gc = gspread.authorize(credentials)
    
    # URL Folder ID (Sebaiknya masukkan di secrets atau hardcode jika folder tetap)
    # Karena gspread butuh membuka file by Name atau Key, kita butuh list file dulu
    # Catatan: gspread murni biasanya buka by filename. 
    # Untuk mencari file di folder spesifik, kita perlu logika filtering nama.
    
    # 1. LOAD KAMUS (Offline Store Kamus)
    # Asumsi nama file di Gdrive pasti mengandung kata "Offline Store Kamus"
    # Kita bisa buka langsung jika nama filenya statis, tapi jika dinamis kita search.
    # Disini saya asumsikan file kamus namanya statis atau kita cari yg paling mirip.
    sh_kamus = gc.open("Offline Store Kamus") # Pastikan nama file di GDrive persis ini
    ws_kamus = sh_kamus.get_worksheet(0)
    df_kamus = pd.DataFrame(ws_kamus.get_all_records())
    
    # LOGIKA PENCARIAN FILE BERDASARKAN POLA NAMA
    # Kita akan list semua spreadsheet yang bisa diakses service account
    # HATI-HATI: Jika file sangat banyak, ini bisa lama.
    all_files = gc.list_spreadsheet_files()
    
    file_export = None
    file_amb = None
    file_bsb = None
    file_mcd = None
    
    for f in all_files:
        name = f['name']
        if "export_" in name and "xlsx" not in name: # Hindari file excel mentah jika ada gsheet
            file_export = f['id']
        elif "Source_AMB" in name:
            file_amb = f['id']
        elif "Source_BSB" in name:
            file_bsb = f['id']
        elif "Source_MCD" in name:
            file_mcd = f['id']
            
    # 2. LOAD SALES DATA (export_xxxx)
    if file_export:
        ws_sales = gc.open_by_key(file_export).get_worksheet(0)
        df_sales = pd.DataFrame(ws_sales.get_all_records())
        # Filter Kolom Sales
        cols_sales = ['Ordernumber', 'Orderdate', 'ItemSKU', 'ItemPrice', 'ItemOrdered']
        df_sales = df_sales[cols_sales]
    else:
        st.error("File 'export_' tidak ditemukan!")
        return None, None

    # 3. LOAD STOCK DATA (AMB, BSB, MCD)
    stock_dfs = []
    
    # Helper untuk load stock
    def get_stock_df(file_id, store_label):
        if file_id:
            ws = gc.open_by_key(file_id).get_worksheet(0)
            df = pd.DataFrame(ws.get_all_records())
            # Pastikan kolom sesuai request
            # Kadang nama kolom di gsheet sensitif case (Location Code vs Location code)
            # Disini saya standarkan nama kolom
            df = df[['Location Code', 'SKU', 'Total']] 
            return df
        return pd.DataFrame()

    df_stock_amb = get_stock_df(file_amb, "AMB")
    df_stock_bsb = get_stock_df(file_bsb, "BSB")
    df_stock_mcd = get_stock_df(file_mcd, "MCD")
    
    # Gabung semua stock
    df_stock_total = pd.concat([df_stock_amb, df_stock_bsb, df_stock_mcd], ignore_index=True)

    return df_sales, df_kamus, df_stock_total

# --- PROSES DATA ---
# ... (Kode bagian atas load_data TETAP SAMA, tidak perlu diubah) ...

# --- PROSES DATA & LOGIC SUPPLY CHAIN ---
try:
    df_sales, df_kamus, df_stock = load_data()
    
    if df_sales is not None and df_stock is not None:
        # 1. DATA PREPARATION
        # Fix Date Format
        df_sales['Orderdate'] = pd.to_datetime(df_sales['Orderdate'], dayfirst=True, errors='coerce')
        df_sales = df_sales.dropna(subset=['Orderdate'])
        
        # Mapping Store ke Sales
        df_sales['POS_Code'] = df_sales['Ordernumber'].astype(str).str[:4]
        df_sales_final = pd.merge(df_sales, df_kamus, left_on='POS_Code', right_on='POS', how='left')
        
        # --- DASHBOARD UI ---
        st.title("🏭 Supply Chain Command Center")
        
        # SIDEBAR FILTER
        st.sidebar.header("Configuration")
        
        # Pilih Store
        all_stores = sorted(df_sales_final['Store_Name'].dropna().unique().tolist())
        selected_store = st.sidebar.selectbox("Select Store Scope:", ["All Stores"] + all_stores)
        
        # Filter Data Berdasarkan Store
        if selected_store != "All Stores":
            sales_filtered = df_sales_final[df_sales_final['Store_Name'] == selected_store]
            stock_filtered = df_stock[df_stock['Location Code'] == selected_store]
        else:
            sales_filtered = df_sales_final
            stock_filtered = df_stock

        # --- CORE CALCULATION (THE BRAIN) ---
        
        # 1. Tentukan Periode 3 Bulan Terakhir (Rolling)
        max_date = sales_filtered['Orderdate'].max()
        start_date_3mo = max_date - pd.DateOffset(days=90)
        
        # 2. Hitung Sales 3 Bulan Terakhir per SKU
        sales_3mo = sales_filtered[sales_filtered['Orderdate'] >= start_date_3mo]
        sku_sales_agg = sales_3mo.groupby('ItemSKU')['ItemOrdered'].sum().reset_index()
        sku_sales_agg.rename(columns={'ItemOrdered': 'Qty_3Mo'}, inplace=True)
        
        # Hitung Average Monthly Sales (AMS)
        sku_sales_agg['AMS'] = sku_sales_agg['Qty_3Mo'] / 3
        
        # 3. Agregasi Stock Saat Ini per SKU
        sku_stock_agg = stock_filtered.groupby('SKU')['Total'].sum().reset_index()
        
        # 4. GABUNGKAN DATA STOCK & SALES (MASTER TABLE)
        # Left join ke stock, karena kita mau analisa inventory yg kita punya
        df_analysis = pd.merge(sku_stock_agg, sku_sales_agg, left_on='SKU', right_on='ItemSKU', how='left')
        
        # Fill NaN (Barang ada stock tapi gak ada sales 3 bulan terakhir)
        df_analysis['AMS'] = df_analysis['AMS'].fillna(0)
        df_analysis['Qty_3Mo'] = df_analysis['Qty_3Mo'].fillna(0)
        
        # 5. HITUNG MONTH COVER
        # Hindari pembagian dengan nol
        import numpy as np
        df_analysis['Month_Cover'] = np.where(
            df_analysis['AMS'] > 0, 
            df_analysis['Total'] / df_analysis['AMS'], 
            999 # Jika sales 0, set angka tinggi (Infinite Cover/Dead Stock)
        )
        
        # 6. KLASIFIKASI STATUS (Logic Bapak)
        def classify_stock(row):
            cover = row['Month_Cover']
            sales = row['AMS']
            
            if sales == 0 and row['Total'] > 0:
                return "Dead Stock / New"
            elif cover < 1.0:
                return "🚨 Reorder Now" # Need Replenishment
            elif 1.0 <= cover <= 1.5:
                return "✅ Healthy"
            else: # > 1.5
                return "⚠️ Overstock"

        df_analysis['Status'] = df_analysis.apply(classify_stock, axis=1)
        
        # --- VISUALISASI PROFESSIONAL ---
        
        # A. TOP LEVEL METRICS
        col1, col2, col3, col4 = st.columns(4)
        
        total_stock_pcs = df_analysis['Total'].sum()
        total_value_est = (sales_filtered['ItemPrice'].mean() * total_stock_pcs) # Estimasi kasar value
        
        # Hitung % Healthy
        count_status = df_analysis['Status'].value_counts()
        pct_healthy = (count_status.get('✅ Healthy', 0) / len(df_analysis)) * 100
        
        col1.metric("Total Stock Qty", f"{total_stock_pcs:,.0f}")
        col2.metric("Active SKUs", f"{len(df_analysis)}")
        col3.metric("Healthy Stock Ratio", f"{pct_healthy:.1f}%")
        col4.metric("Last Sales Date", max_date.strftime('%d %b %Y'))
        
        st.markdown("---")
        
        # B. STOCK COMPOSITION & ACTION PLAN
        c1, c2 = st.columns([1, 2])
        
        with c1:
            st.subheader("Stock Health Composition")
            st.bar_chart(df_analysis['Status'].value_counts())
            
            st.info("""
            **Logic Klasifikasi:**
            - **Reorder:** Cover < 1 Bulan
            - **Healthy:** Cover 1 - 1.5 Bulan
            - **Overstock:** Cover > 1.5 Bulan
            """)
            
        with c2:
            st.subheader("⚠️ Priority Action: Reorder Needed")
            # Filter hanya yang butuh reorder
            reorder_df = df_analysis[df_analysis['Status'] == "🚨 Reorder Now"].sort_values('Month_Cover')
            
            # Tampilkan tabel simple
            st.dataframe(
                reorder_df[['SKU', 'Total', 'AMS', 'Month_Cover']],
                column_config={
                    "Month_Cover": st.column_config.NumberColumn(
                        "Cover (Months)", format="%.1f m"
                    ),
                    "AMS": st.column_config.NumberColumn(
                        "Avg Sales/Mo", format="%.1f"
                    )
                },
                hide_index=True,
                use_container_width=True
            )

        st.markdown("---")

        # C. DEEP DIVE: SKU MASTER TABLE
        st.subheader("🔍 Detailed Inventory Analysis")
        
        # Tambahkan visual highlight pada tabel
        # Kita pakai Pandas Styler untuk mewarnai row/cell (Advanced)
        
        # Filter Table Interactive
        filter_status = st.multiselect("Filter by Status:", df_analysis['Status'].unique(), default=df_analysis['Status'].unique())
        df_view = df_analysis[df_analysis['Status'].isin(filter_status)]
        
        # Tampilkan
        st.dataframe(
            df_view[['SKU', 'Status', 'Total', 'Qty_3Mo', 'AMS', 'Month_Cover']],
            column_config={
                "Status": st.column_config.TextColumn("Health Status"),
                "Total": st.column_config.ProgressColumn(
                    "Current Stock", format="%d", min_value=0, max_value=int(df_analysis['Total'].max())
                ),
                "Month_Cover": st.column_config.NumberColumn(
                    "Month Cover", format="%.1f x", help="Stock / Avg Monthly Sales"
                )
            },
            hide_index=True,
            use_container_width=True,
            height=500
        )
        
        # Download Button
        csv = df_view.to_csv(index=False).encode('utf-8')
        st.download_button(
            "📥 Download Analysis Report",
            csv,
            "supply_chain_report.csv",
            "text/csv",
            key='download-csv'
        )

    else:
        st.warning("Data Sales atau Stock belum berhasil di-load sepenuhnya.")

except Exception as e:
    st.error(f"Terjadi kesalahan logic: {e}")
    # Print detail error untuk debugging
    import traceback
    st.text(traceback.format_exc())
