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
try:
    df_sales, df_kamus, df_stock = load_data()
    
    if df_sales is not None:
        # 1. MAPPING STORE NAME KE SALES
        # Ambil 4 karakter kiri dari Ordernumber
        df_sales['POS_Code'] = df_sales['Ordernumber'].astype(str).str[:4]
        
        # Merge dengan Kamus (POS -> Store_Name)
        # Pastikan kolom di df_kamus namanya 'POS' dan 'Store_Name' sesuai gambar
        df_sales_final = pd.merge(df_sales, df_kamus, left_on='POS_Code', right_on='POS', how='left')
        
        # Convert Date
        # Tambahkan parameter dayfirst=True agar membaca format DD/MM/YYYY
        df_sales_final['Orderdate'] = pd.to_datetime(df_sales_final['Orderdate'], dayfirst=True, errors='coerce')
        
        # (Opsional) Hapus data yang tanggalnya error/kosong agar grafik tidak error
        df_sales_final = df_sales_final.dropna(subset=['Orderdate'])
        
        # --- DASHBOARD UI ---
        st.title("🏭 Dashboard Flagship Store")
        
        # Filter Sidebar
        st.sidebar.header("Filter")
        selected_store = st.sidebar.multiselect(
            "Pilih Store", 
            options=df_sales_final['Store_Name'].unique(),
            default=df_sales_final['Store_Name'].unique()
        )
        
        # Filter Data
        filtered_sales = df_sales_final[df_sales_final['Store_Name'].isin(selected_store)]
        filtered_stock = df_stock[df_stock['Location Code'].isin(selected_store)]
        
        # KPI Utama
        col1, col2, col3 = st.columns(3)
        total_omset = (filtered_sales['ItemPrice'] * filtered_sales['ItemOrdered']).sum()
        total_qty_sold = filtered_sales['ItemOrdered'].sum()
        total_stock = filtered_stock['Total'].sum()
        
        col1.metric("Total Revenue", f"Rp {total_omset:,.0f}")
        col2.metric("Items Sold", f"{total_qty_sold} Pcs")
        col3.metric("Current Stock", f"{total_stock} Pcs")
        
        st.divider()
        
        # TABS VISUALISASI
        tab1, tab2 = st.tabs(["📊 Sales Analysis", "📦 Stock Monitor"])
        
        with tab1:
            st.subheader("Tren Penjualan Harian")
            daily_sales = filtered_sales.groupby('Orderdate')['ItemOrdered'].sum().reset_index()
            st.line_chart(daily_sales, x='Orderdate', y='ItemOrdered')
            
            st.subheader("Raw Data Sales")
            st.dataframe(filtered_sales)
            
        with tab2:
            st.subheader("Posisi Stock per SKU")
            # Group by SKU agar rapi
            stock_by_sku = filtered_stock.groupby('SKU')['Total'].sum().sort_values(ascending=False).head(20)
            st.bar_chart(stock_by_sku)
            
            st.subheader("Raw Data Stock")
            st.dataframe(filtered_stock)

except Exception as e:
    st.error(f"Terjadi kesalahan: {e}")
    st.info("Pastikan nama kolom di Google Sheet persis dengan yang diminta (Case Sensitive).")
