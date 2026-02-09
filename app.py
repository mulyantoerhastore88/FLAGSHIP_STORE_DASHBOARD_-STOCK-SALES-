import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- KONFIGURASI HALAMAN PROFESIONAL ---
st.set_page_config(
    page_title="Supply Chain Command Center | Flagship Store",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CUSTOM CSS UNTUK TAMPILAN PREMIUM ---
st.markdown("""
<style>
    .main-header {
        font-size: 2.8rem !important;
        color: #1E3A8A !important;
        font-weight: 700;
        padding-bottom: 0.5rem;
        border-bottom: 3px solid #3B82F6;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 15px;
        color: white;
        box-shadow: 0 10px 20px rgba(0,0,0,0.1);
    }
    .metric-title {
        font-size: 0.9rem;
        opacity: 0.9;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 0.5rem;
    }
    .metric-value {
        font-size: 2.2rem !important;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }
    .metric-change {
        font-size: 0.9rem;
        opacity: 0.9;
    }
    .inventory-table {
        background: white;
        border-radius: 10px;
        overflow: hidden;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        margin: 1rem 0;
    }
    .store-header {
        background: linear-gradient(90deg, #3B82F6, #1D4ED8);
        color: white;
        padding: 1rem;
        font-weight: 600;
        border-bottom: 2px solid #1D4ED8;
    }
    .control-header {
        background: #10B981;
        color: white;
        padding: 0.75rem;
        font-weight: 500;
    }
    .total-header {
        background: #6366F1;
        color: white;
        padding: 0.75rem;
        font-weight: 600;
    }
    .data-cell {
        padding: 0.75rem;
        border-bottom: 1px solid #E5E7EB;
    }
    .status-badge {
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
        display: inline-block;
    }
    .stProgress > div > div > div > div {
        background-color: #3B82F6;
    }
    .store-card {
        background: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        border-left: 4px solid #3B82F6;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# --- KONEKSI KE GOOGLE SHEETS (DI CACHE) ---
@st.cache_data(ttl=300, show_spinner="🔄 Loading real-time data from Google Sheets...")
def load_data():
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scope
    )
    gc = gspread.authorize(credentials)
    
    # Load Kamus Store (Sheet 1) dan SKU Kamus (Sheet 2)
    try:
        sh_kamus = gc.open("Offline Store Kamus")
        
        # Sheet 1: Store Kamus dengan kolom Store (kolom C)
        ws_store_kamus = sh_kamus.get_worksheet(0)
        df_store_kamus = pd.DataFrame(ws_store_kamus.get_all_records())
        
        # Validasi kolom Store
        if 'Store' not in df_store_kamus.columns:
            st.warning("⚠️ Kolom 'Store' tidak ditemukan di Sheet 1. Menggunakan POS sebagai fallback.")
            if 'POS' in df_store_kamus.columns:
                df_store_kamus['Store'] = df_store_kamus['POS']
        
        # Sheet 2: SKU Kamus (SKU dan Kategori)
        ws_sku_kamus = sh_kamus.get_worksheet(1)
        df_sku_kamus = pd.DataFrame(ws_sku_kamus.get_all_records())
        
        # Validasi kolom
        if 'SKU' not in df_sku_kamus.columns:
            st.error("❌ Kolom 'SKU' tidak ditemukan di Sheet 2")
            df_sku_kamus = pd.DataFrame()
        if 'SKU_Category' not in df_sku_kamus.columns:
            st.error("❌ Kolom 'SKU_Category' tidak ditemukan di Sheet 2")
            df_sku_kamus = pd.DataFrame()
            
    except Exception as e:
        st.error(f"⚠️ Error loading kamus data: {e}")
        df_store_kamus = pd.DataFrame()
        df_sku_kamus = pd.DataFrame()
    
    # List semua spreadsheet
    all_files = gc.list_spreadsheet_files()
    
    # Cari file berdasarkan pattern
    file_ids = {
        'export': None,
        'amb': None,
        'bsb': None,
        'mcd': None
    }
    
    for f in all_files:
        name = f['name'].lower()
        if 'export_' in name and 'xlsx' not in name:
            file_ids['export'] = f['id']
        elif 'source_amb' in name:
            file_ids['amb'] = f['id']
        elif 'source_bsb' in name:
            file_ids['bsb'] = f['id']
        elif 'source_mcd' in name:
            file_ids['mcd'] = f['id']
    
    # Load Sales Data
    if file_ids['export']:
        ws_sales = gc.open_by_key(file_ids['export']).get_worksheet(0)
        df_sales = pd.DataFrame(ws_sales.get_all_records())
        cols_sales = ['Ordernumber', 'Orderdate', 'ItemSKU', 'ItemPrice', 'ItemOrdered']
        df_sales = df_sales[cols_sales] if all(col in df_sales.columns for col in cols_sales) else df_sales
    else:
        st.error("❌ File sales (export_) tidak ditemukan!")
        df_sales = pd.DataFrame()
    
    # Load Stock Data
    stock_dfs = []
    store_mapping = {'amb': 'AMB', 'bsb': 'BSB', 'mcd': 'MCD'}
    
    for key, store_name in store_mapping.items():
        if file_ids[key]:
            try:
                ws = gc.open_by_key(file_ids[key]).get_worksheet(0)
                df = pd.DataFrame(ws.get_all_records())
                if len(df) > 0:
                    # Standardize column names
                    col_mapping = {}
                    for col in df.columns:
                        col_lower = col.lower()
                        if 'location' in col_lower or 'store' in col_lower:
                            col_mapping[col] = 'Location Code'
                        elif 'sku' in col_lower:
                            col_mapping[col] = 'SKU'
                        elif 'total' in col_lower or 'stock' in col_lower or 'qty' in col_lower:
                            col_mapping[col] = 'Total'
                    
                    df = df.rename(columns=col_mapping)
                    required_cols = ['Location Code', 'SKU', 'Total']
                    
                    if all(col in df.columns for col in required_cols):
                        df['Store_Name'] = store_name
                        stock_dfs.append(df[['Location Code', 'SKU', 'Total', 'Store_Name']])
            except Exception as e:
                st.warning(f"⚠️ Gagal load stock data untuk {store_name}: {e}")
    
    df_stock_total = pd.concat(stock_dfs, ignore_index=True) if stock_dfs else pd.DataFrame()
    
    return df_sales, df_store_kamus, df_sku_kamus, df_stock_total

# --- FUNGSI UNTUK INVENTORY CONTROL TABLE ---
def create_inventory_control_table(analysis_df, sales_data, store_name, store_display_name=None):
    """Membuat tabel Inventory Control seperti yang diinginkan"""
    
    if store_display_name is None:
        store_display_name = store_name
    
    # Filter data untuk store tertentu
    store_data = analysis_df[analysis_df['Store_Name'] == store_name].copy()
    
    if store_data.empty:
        return None
    
    # Hitung metrics berdasarkan status
    status_counts = store_data['Status'].value_counts()
    
    # Mapping status ke kategori control
    ideal_count = status_counts.get('✅ Healthy', 0) + status_counts.get('📈 Good Buffer', 0)
    need_replenishment = status_counts.get('🚨 Critical', 0) + status_counts.get('⚠️ Need Reorder', 0)
    over_stock = status_counts.get('🛑 Overstock', 0)
    non_moving = status_counts.get('📦 New/Dead Stock', 0)
    
    # Hitung total metrics
    count_of_sku = len(store_data)
    qty_stock = store_data['Total'].sum()
    avg_sales = store_data['AMS'].sum()
    
    # Hitung Week Cover (Month Cover / 4.33)
    store_data['Week_Cover'] = store_data['Month_Cover'] * (30/7) / 4.33  # Konversi bulan ke minggu
    avg_weekcover = store_data['Week_Cover'].median()
    
    # Hitung Replenishment Quantity Suggested (untuk yang perlu reorder)
    reorder_data = store_data[store_data['Status'].isin(['🚨 Critical', '⚠️ Need Reorder'])]
    if not reorder_data.empty:
        reorder_data['Replenishment_Suggest'] = np.where(
            reorder_data['Month_Cover'] < 1,
            (reorder_data['AMS'] * 1.5 - reorder_data['Total']).clip(lower=0),
            (reorder_data['AMS'] * 0.5).clip(lower=0)
        )
        replenishment_qty_suggest = reorder_data['Replenishment_Suggest'].sum()
    else:
        replenishment_qty_suggest = 0
    
    # Buat dictionary untuk tabel
    control_data = {
        'Metric': ['Ideal Stock', 'Need Replenishment', 'Over Stock', 'Non Moving Stock', 
                   'Count of SKU', 'Qty Stock', 'AVG Sales', 'Replenishment Qty Suggest', 'Weekcover'],
        'Value': [
            int(ideal_count),
            int(need_replenishment),
            int(over_stock),
            int(non_moving),
            int(count_of_sku),
            f"{int(qty_stock):,}",
            f"{int(avg_sales):,}",
            f"{int(replenishment_qty_suggest):,}",
            f"{avg_weekcover:.1f}"
        ]
    }
    
    # Buat DataFrame untuk Control section
    control_df = pd.DataFrame(control_data)
    
    # Buat Grand Total section
    grand_total_data = {
        'Metric': ['Count of SKU', 'Qty Stock', 'AVG Sales', 'Replenishment Qty Suggest', 'Weekcover'],
        'Value': [
            f"**{int(count_of_sku)}**",
            f"**{int(qty_stock):,}**",
            f"**{int(avg_sales):,}**",
            f"**{int(replenishment_qty_suggest):,}**",
            f"**{avg_weekcover:.1f}**"
        ]
    }
    
    grand_total_df = pd.DataFrame(grand_total_data)
    
    return {
        'store_name': store_display_name,
        'control_df': control_df,
        'grand_total_df': grand_total_df,
        'raw_metrics': {
            'ideal_stock': int(ideal_count),
            'need_replenishment': int(need_replenishment),
            'over_stock': int(over_stock),
            'non_moving': int(non_moving),
            'count_of_sku': int(count_of_sku),
            'qty_stock': int(qty_stock),
            'avg_sales': int(avg_sales),
            'replenishment_qty_suggest': int(replenishment_qty_suggest),
            'weekcover': avg_weekcover
        }
    }

# --- FUNGSI HELPER UNTUK ANALISIS DENGAN FILTER SKU ---
def filter_by_sku_kamus(df, sku_kamus):
    """Filter dataframe hanya untuk SKU yang ada di SKU Kamus"""
    if sku_kamus.empty:
        return df
    
    valid_skus = sku_kamus['SKU'].astype(str).str.strip().unique()
    
    if 'ItemSKU' in df.columns:
        # Untuk sales data
        df_filtered = df[df['ItemSKU'].astype(str).str.strip().isin(valid_skus)].copy()
        # Tambahkan kategori SKU
        sku_mapping = sku_kamus.set_index('SKU')['SKU_Category'].to_dict()
        df_filtered['SKU_Category'] = df_filtered['ItemSKU'].astype(str).str.strip().map(sku_mapping)
    
    elif 'SKU' in df.columns:
        # Untuk stock data
        df_filtered = df[df['SKU'].astype(str).str.strip().isin(valid_skus)].copy()
        # Tambahkan kategori SKU
        sku_mapping = sku_kamus.set_index('SKU')['SKU_Category'].to_dict()
        df_filtered['SKU_Category'] = df_filtered['SKU'].astype(str).str.strip().map(sku_mapping)
    
    else:
        return df
    
    return df_filtered

def calculate_stock_health(df_stock, df_sales_mapped, sku_kamus, store_name=None):
    """Hitung health metrics untuk stock (hanya SKU yang ada di kamus)"""
    
    # Filter hanya SKU yang ada di kamus
    df_stock_filtered = filter_by_sku_kamus(df_stock, sku_kamus)
    df_sales_filtered = filter_by_sku_kamus(df_sales_mapped, sku_kamus)
    
    if store_name:
        stock_data = df_stock_filtered[df_stock_filtered['Store_Name'] == store_name].copy()
        sales_data = df_sales_filtered[df_sales_filtered['Store_Name'] == store_name].copy()
    else:
        stock_data = df_stock_filtered.copy()
        sales_data = df_sales_filtered.copy()
    
    if stock_data.empty:
        return pd.DataFrame()
    
    # Hitung sales 3 bulan terakhir per SKU
    current_date = datetime.now()
    start_date_3mo = current_date - timedelta(days=90)
    
    sales_data['Orderdate'] = pd.to_datetime(sales_data['Orderdate'], errors='coerce')
    recent_sales = sales_data[sales_data['Orderdate'] >= start_date_3mo]
    
    if not recent_sales.empty:
        sku_sales = recent_sales.groupby('ItemSKU').agg({
            'ItemOrdered': 'sum',
            'ItemPrice': 'mean'
        }).reset_index()
        sku_sales.columns = ['SKU', 'Qty_3Mo', 'Avg_Price']
        sku_sales['AMS'] = sku_sales['Qty_3Mo'] / 3
    else:
        # Buat dataframe kosong jika tidak ada sales
        sku_sales = pd.DataFrame(columns=['SKU', 'Qty_3Mo', 'Avg_Price', 'AMS'])
    
    # Gabungkan dengan stock
    analysis_df = stock_data.groupby(['SKU', 'Store_Name', 'SKU_Category']).agg({'Total': 'sum'}).reset_index()
    
    if not sku_sales.empty:
        analysis_df = pd.merge(analysis_df, sku_sales, on='SKU', how='left')
    else:
        analysis_df['Qty_3Mo'] = 0
        analysis_df['Avg_Price'] = analysis_df['Total'].median()  # Default price
        analysis_df['AMS'] = 0
    
    # Fill NaN values
    analysis_df['Qty_3Mo'] = analysis_df['Qty_3Mo'].fillna(0)
    analysis_df['AMS'] = analysis_df['AMS'].fillna(0)
    analysis_df['Avg_Price'] = analysis_df['Avg_Price'].fillna(analysis_df['Avg_Price'].median() if not analysis_df['Avg_Price'].isna().all() else 0)
    
    # Hitung Month Cover
    analysis_df['Month_Cover'] = np.where(
        analysis_df['AMS'] > 0,
        analysis_df['Total'] / analysis_df['AMS'],
        999  # Jika tidak ada sales
    )
    
    # Hitung nilai stock
    analysis_df['Stock_Value'] = analysis_df['Total'] * analysis_df['Avg_Price']
    
    # Klasifikasi Status (dengan mapping yang sesuai untuk inventory control)
    def classify_status(row):
        if row['Total'] > 0 and row['AMS'] == 0:
            return "📦 New/Dead Stock"  # Non Moving Stock
        elif row['Month_Cover'] < 0.5:
            return "🚨 Critical"  # Need Replenishment
        elif row['Month_Cover'] < 1:
            return "⚠️ Need Reorder"  # Need Replenishment
        elif row['Month_Cover'] <= 1.5:
            return "✅ Healthy"  # Ideal Stock
        elif row['Month_Cover'] <= 3:
            return "📈 Good Buffer"  # Ideal Stock
        else:
            return "🛑 Overstock"  # Over Stock
    
    analysis_df['Status'] = analysis_df.apply(classify_status, axis=1)
    
    # Urutan status untuk sorting
    status_order = {
        "🚨 Critical": 1,
        "⚠️ Need Reorder": 2,
        "✅ Healthy": 3,
        "📈 Good Buffer": 4,
        "🛑 Overstock": 5,
        "📦 New/Dead Stock": 6
    }
    analysis_df['Status_Order'] = analysis_df['Status'].map(status_order)
    
    return analysis_df.sort_values('Status_Order')

# --- MAIN DASHBOARD ---
try:
    # Header dengan gradient premium
    st.markdown("""
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                padding: 2rem; 
                border-radius: 15px; 
                margin-bottom: 2rem;
                color: white;">
        <h1 style="color: white; margin: 0; font-size: 2.8rem;">🏭 Flagship Store Inventory Control</h1>
        <p style="opacity: 0.9; font-size: 1.1rem; margin-top: 0.5rem;">Dashboard Monitoring & Replenishment System</p>
        <p style="opacity: 0.8; font-size: 0.9rem; margin-top: 0.2rem;">As of: """ + datetime.now().strftime("%d/%m/%Y") + """</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Load data dengan spinner yang elegan
    with st.spinner("🔄 Loading real-time data from Google Sheets..."):
        df_sales, df_store_kamus, df_sku_kamus, df_stock = load_data()
    
    if df_sales.empty or df_stock.empty or df_sku_kamus.empty:
        st.error("❌ Data tidak dapat dimuat. Pastikan file SKU Kamus (Sheet 2) sudah terisi dengan benar.")
        st.stop()
    
    # Tampilkan summary SKU Kamus
    with st.expander("📋 SKU Kamus Summary", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total SKU in Kamus", len(df_sku_kamus))
        with col2:
            category_counts = df_sku_kamus['SKU_Category'].value_counts()
            st.metric("Categories", len(category_counts))
        with col3:
            st.metric("Sample SKU", df_sku_kamus['SKU'].iloc[0] if len(df_sku_kamus) > 0 else "N/A")
        
        st.dataframe(df_sku_kamus, use_container_width=True, height=200)
    
    # --- DATA PREPARATION DENGAN FILTER SKU ---
    df_sales['Orderdate'] = pd.to_datetime(df_sales['Orderdate'], dayfirst=True, errors='coerce')
    df_sales = df_sales.dropna(subset=['Orderdate'])
    
    # Mapping store code dengan nama store dari kolom Store
    df_sales['POS_Code'] = df_sales['Ordernumber'].astype(str).str[:4]
    
    # Merge dengan store kamus untuk mendapatkan nama store
    if 'Store' in df_store_kamus.columns:
        store_mapping = df_store_kamus.set_index('POS')['Store'].to_dict()
        df_sales_mapped = df_sales.copy()
        df_sales_mapped['Store_Name'] = df_sales_mapped['POS_Code'].map(store_mapping)
        
        # Update store names di stock data jika ada mapping
        if 'Location Code' in df_stock.columns:
            df_stock['Store_Name'] = df_stock['Location Code'].map(store_mapping)
            df_stock['Store_Name'] = df_stock['Store_Name'].fillna(df_stock['Store_Name'])  # Keep original if no mapping
    else:
        # Fallback jika tidak ada kolom Store
        df_sales_mapped = pd.merge(df_sales, df_store_kamus, left_on='POS_Code', right_on='POS', how='left')
        df_sales_mapped['Store_Name'] = df_sales_mapped['Store_Name']  # Use existing column
    
    # --- SIDEBAR FILTER PROFESIONAL ---
    with st.sidebar:
        st.markdown("### ⚙️ Dashboard Configuration")
        
        # Date Display
        st.markdown(f"**📅 Date: {datetime.now().strftime('%d/%m/%Y')}**")
        
        # SKU Category Filter (dari SKU Kamus)
        st.markdown("**📊 SKU Category Filter**")
        sku_categories = sorted(df_sku_kamus['SKU_Category'].dropna().unique().tolist())
        selected_categories = st.multiselect(
            "Select SKU Categories:",
            options=sku_categories,
            default=sku_categories
        )
        
        # Store Selection
        st.markdown("**🏪 Store Selection**")
        available_stores = sorted(df_stock['Store_Name'].dropna().unique().tolist())
        store_options = ["All Stores"] + available_stores
        selected_stores = st.multiselect(
            "Select Stores:",
            options=store_options[1:],
            default=store_options[1:] if len(store_options) > 1 else []
        )
        
        if not selected_stores:
            selected_stores = available_stores
        
        # Display Mode
        st.markdown("**📱 Display Mode**")
        display_mode = st.radio(
            "Table Display:",
            ["Detailed View", "Summary View"],
            index=0
        )
    
    # Filter SKU Kamus berdasarkan kategori yang dipilih
    df_sku_kamus_filtered = df_sku_kamus[df_sku_kamus['SKU_Category'].isin(selected_categories)] if selected_categories else df_sku_kamus
    
    # Filter data berdasarkan pilihan store
    stock_filtered = df_stock[df_stock['Store_Name'].isin(selected_stores)] if selected_stores else df_stock
    sales_filtered = df_sales_mapped[df_sales_mapped['Store_Name'].isin(selected_stores)] if selected_stores else df_sales_mapped
    
    # Hitung metrics utama dengan filter SKU
    analysis_df = calculate_stock_health(stock_filtered, sales_filtered, df_sku_kamus_filtered)
    
    # --- KPI CARDS ---
    st.markdown("### 📈 Executive Summary")
    
    if not analysis_df.empty:
        total_stock_value = analysis_df['Stock_Value'].sum()
        total_skus = analysis_df['SKU'].nunique()
        total_units = analysis_df['Total'].sum()
        
        # Hitung distribusi status
        status_counts = analysis_df['Status'].value_counts()
        ideal_count = status_counts.get('✅ Healthy', 0) + status_counts.get('📈 Good Buffer', 0)
        need_replenishment = status_counts.get('🚨 Critical', 0) + status_counts.get('⚠️ Need Reorder', 0)
        over_stock = status_counts.get('🛑 Overstock', 0)
        non_moving = status_counts.get('📦 New/Dead Stock', 0)
        
        total_items = status_counts.sum()
        
        # Display KPI Cards
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">Total Stock Value</div>
                <div class="metric-value">Rp {total_stock_value:,.0f}</div>
                <div class="metric-change">{total_skus} SKUs | {total_units:,} Units</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            health_percentage = (ideal_count / total_items * 100) if total_items > 0 else 0
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">Ideal Stock Ratio</div>
                <div class="metric-value">{health_percentage:.1f}%</div>
                <div class="metric-change">{ideal_count} of {total_items} SKUs</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">Need Replenishment</div>
                <div class="metric-value">{need_replenishment}</div>
                <div class="metric-change">SKUs Require Action</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col4:
            avg_cover = analysis_df[analysis_df['Month_Cover'] < 50]['Month_Cover'].median()
            avg_cover = 0 if pd.isna(avg_cover) else avg_cover
            avg_weekcover = avg_cover * (30/7) / 4.33
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">Avg. Week Cover</div>
                <div class="metric-value">{avg_weekcover:.1f}</div>
                <div class="metric-change">Weeks of Inventory</div>
            </div>
            """, unsafe_allow_html=True)
    
    # --- TABBED INTERFACE ---
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Inventory Control", "📊 Store Overview", "🚨 Priority Actions", "📈 Trends & Analysis"])
    
    with tab1:
        st.markdown(f"### 🏪 Flagship Store Inventory Control - {datetime.now().strftime('%d/%m/%Y')}")
        
        if not analysis_df.empty:
            # Buat inventory control table untuk setiap store
            inventory_tables = []
            
            for store in sorted(analysis_df['Store_Name'].unique()):
                # Ambil nama display dari mapping jika ada
                store_display_name = store
                if 'Store' in df_store_kamus.columns:
                    store_row = df_store_kamus[df_store_kamus['POS'] == store]
                    if not store_row.empty and 'Store' in store_row.columns:
                        store_display_name = store_row.iloc[0]['Store']
                
                # Buat inventory control table
                table_data = create_inventory_control_table(analysis_df, sales_filtered, store, store_display_name)
                
                if table_data:
                    inventory_tables.append(table_data)
                    
                    # Tampilkan tabel
                    st.markdown(f"""
                    <div class="inventory-table">
                        <div class="store-header">
                            Store Name: {table_data['store_name']}
                        </div>
                        <div class="control-header">
                            Control
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Tampilkan Control section
                    control_cols = st.columns(3)
                    items_per_col = 3  # 9 items total, 3 per column
                    
                    for i in range(3):
                        with control_cols[i]:
                            start_idx = i * items_per_col
                            end_idx = start_idx + items_per_col
                            for j in range(start_idx, min(end_idx, len(table_data['control_df']))):
                                row = table_data['control_df'].iloc[j]
                                col1, col2 = st.columns([2, 1])
                                with col1:
                                    st.markdown(f"**{row['Metric']}**")
                                with col2:
                                    st.markdown(f"**{row['Value']}**")
                    
                    # Tampilkan Grand Total section
                    st.markdown(f"""
                    <div class="inventory-table">
                        <div class="total-header">
                            {table_data['store_name']} Total
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Tampilkan Grand Total metrics
                    total_cols = st.columns(5)
                    for idx, (col, (_, row)) in enumerate(zip(total_cols, table_data['grand_total_df'].iterrows())):
                        with col:
                            st.markdown(f"""
                            <div style="text-align: center; padding: 0.5rem; background: #F3F4F6; border-radius: 8px;">
                                <div style="font-size: 0.8rem; color: #6B7280;">{row['Metric']}</div>
                                <div style="font-size: 1.2rem; font-weight: 700; color: #1F2937;">{row['Value'].replace('**', '')}</div>
                            </div>
                            """, unsafe_allow_html=True)
                    
                    st.markdown("---")
            
            # Summary Across All Stores
            if len(inventory_tables) > 1:
                st.markdown("### 📊 Summary Across All Stores")
                
                # Buat summary dataframe
                summary_data = []
                for table in inventory_tables:
                    summary_data.append({
                        'Store': table['store_name'],
                        'Ideal Stock': table['raw_metrics']['ideal_stock'],
                        'Need Replenishment': table['raw_metrics']['need_replenishment'],
                        'Over Stock': table['raw_metrics']['over_stock'],
                        'Non Moving': table['raw_metrics']['non_moving'],
                        'SKU Count': table['raw_metrics']['count_of_sku'],
                        'Qty Stock': table['raw_metrics']['qty_stock'],
                        'Weekcover': table['raw_metrics']['weekcover']
                    })
                
                summary_df = pd.DataFrame(summary_data)
                
                # Tampilkan summary table
                st.dataframe(
                    summary_df,
                    column_config={
                        "Store": st.column_config.TextColumn("Store Name"),
                        "Ideal Stock": st.column_config.NumberColumn(
                            "Ideal",
                            help="SKUs with healthy stock level",
                            format="%d"
                        ),
                        "Need Replenishment": st.column_config.NumberColumn(
                            "Need Repl.",
                            help="SKUs that need replenishment",
                            format="%d"
                        ),
                        "Over Stock": st.column_config.NumberColumn(
                            "Over Stock",
                            help="SKUs with overstock condition",
                            format="%d"
                        ),
                        "Non Moving": st.column_config.NumberColumn(
                            "Non Moving",
                            help="SKUs with no sales in last 3 months",
                            format="%d"
                        ),
                        "Weekcover": st.column_config.NumberColumn(
                            "Weekcover",
                            format="%.1f weeks"
                        )
                    },
                    use_container_width=True,
                    hide_index=True
                )
                
                # Visualisasi summary
                col1, col2 = st.columns(2)
                
                with col1:
                    # Bar chart untuk SKU distribution
                    fig1 = px.bar(summary_df, x='Store', y=['Ideal Stock', 'Need Replenishment', 'Over Stock', 'Non Moving'],
                                title='SKU Distribution by Store',
                                barmode='group')
                    fig1.update_layout(height=400)
                    st.plotly_chart(fig1, use_container_width=True)
                
                with col2:
                    # Pie chart untuk total distribution
                    total_ideal = summary_df['Ideal Stock'].sum()
                    total_replenish = summary_df['Need Replenishment'].sum()
                    total_over = summary_df['Over Stock'].sum()
                    total_non_moving = summary_df['Non Moving'].sum()
                    
                    fig2 = px.pie(
                        values=[total_ideal, total_replenish, total_over, total_non_moving],
                        names=['Ideal Stock', 'Need Replenishment', 'Over Stock', 'Non Moving'],
                        title='Total SKU Distribution Across All Stores',
                        color=['Ideal Stock', 'Need Replenishment', 'Over Stock', 'Non Moving'],
                        color_discrete_map={
                            'Ideal Stock': '#10B981',
                            'Need Replenishment': '#F59E0B',
                            'Over Stock': '#EF4444',
                            'Non Moving': '#6B7280'
                        }
                    )
                    fig2.update_layout(height=400)
                    st.plotly_chart(fig2, use_container_width=True)
    
    with tab2:
        st.markdown("### 🏪 Store Performance Overview")
        
        if not analysis_df.empty:
            # Group by store analysis
            store_summary = analysis_df.groupby('Store_Name').agg({
                'SKU': 'nunique',
                'Total': 'sum',
                'Stock_Value': 'sum',
                'Month_Cover': 'median',
                'Status': lambda x: (x.isin(['✅ Healthy', '📈 Good Buffer'])).sum() / len(x) * 100
            }).round(2).reset_index()
            
            store_summary.columns = ['Store', 'SKU Count', 'Total Units', 'Stock Value', 'Avg Month Cover', 'Health %']
            
            # Display store cards
            cols = st.columns(len(store_summary))
            for idx, (col, (_, row)) in enumerate(zip(cols, store_summary.iterrows())):
                with col:
                    health_color = "#10B981" if row['Health %'] > 70 else "#F59E0B" if row['Health %'] > 40 else "#EF4444"
                    st.markdown(f"""
                    <div class="store-card">
                        <h4 style="margin: 0 0 10px 0;">{row['Store']}</h4>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                            <span style="font-size: 0.9rem; opacity: 0.7;">SKUs:</span>
                            <span style="font-weight: 600;">{int(row['SKU Count'])}</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                            <span style="font-size: 0.9rem; opacity: 0.7;">Units:</span>
                            <span style="font-weight: 600;">{int(row['Total Units']):,}</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                            <span style="font-size: 0.9rem; opacity: 0.7;">Health:</span>
                            <span style="font-weight: 600; color: {health_color};">{row['Health %']:.1f}%</span>
                        </div>
                        <div style="margin-top: 10px; background: #f3f4f6; border-radius: 5px; padding: 5px;">
                            <div style="font-size: 0.8rem; opacity: 0.7;">Week Cover:</div>
                            <div style="font-weight: 700; font-size: 1.2rem;">{(row['Avg Month Cover'] * (30/7) / 4.33):.1f}</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
            
            # Store comparison chart
            st.markdown("#### Store Comparison Analysis")
            
            col1, col2 = st.columns(2)
            
            with col1:
                fig1 = px.bar(store_summary, x='Store', y='Health %',
                            title='Stock Health Score by Store',
                            color='Health %',
                            color_continuous_scale='RdYlGn')
                fig1.update_layout(height=400)
                st.plotly_chart(fig1, use_container_width=True)
            
            with col2:
                # Stacked bar chart untuk status distribution per store
                status_by_store = analysis_df.groupby(['Store_Name', 'Status']).size().unstack(fill_value=0)
                fig2 = px.bar(status_by_store, 
                            title='Status Distribution by Store',
                            barmode='stack')
                fig2.update_layout(height=400)
                st.plotly_chart(fig2, use_container_width=True)
    
    with tab3:
        st.markdown("### 🚨 Priority Action Items")
        
        # Filter SKUs yang butuh perhatian
        priority_items = analysis_df[analysis_df['Status'].isin(['🚨 Critical', '⚠️ Need Reorder'])]
        
        if not priority_items.empty:
            # Group by store untuk reorder recommendations
            for store in priority_items['Store_Name'].unique():
                store_items = priority_items[priority_items['Store_Name'] == store]
                
                with st.expander(f"**{store}** - {len(store_items)} SKUs Need Attention", expanded=True):
                    # Calculate recommended order quantity
                    store_items = store_items.copy()
                    store_items['Recommended_Order'] = np.where(
                        store_items['Month_Cover'] < 1,
                        (store_items['AMS'] * 1.5 - store_items['Total']).clip(lower=1),
                        (store_items['AMS'] * 0.5).clip(lower=1)
                    )
                    
                    # Display table
                    display_cols = ['SKU', 'SKU_Category', 'Total', 'AMS', 'Month_Cover', 'Recommended_Order', 'Status']
                    styled_df = store_items[display_cols].sort_values('Month_Cover')
                    
                    # Format untuk display
                    styled_df['Month_Cover'] = styled_df['Month_Cover'].apply(lambda x: f"{x:.1f}x")
                    styled_df['Week_Cover'] = (styled_df['Month_Cover'].str.replace('x', '').astype(float) * (30/7) / 4.33).apply(lambda x: f"{x:.1f}")
                    styled_df['Recommended_Order'] = styled_df['Recommended_Order'].apply(lambda x: f"{int(x)} pcs")
                    styled_df['AMS'] = styled_df['AMS'].apply(lambda x: f"{x:.1f}/month")
                    
                    st.dataframe(
                        styled_df,
                        column_config={
                            "Status": st.column_config.TextColumn(
                                width="small",
                                help="Stock status classification"
                            ),
                            "Week_Cover": st.column_config.NumberColumn(
                                "Week Cover",
                                format="%.1f w"
                            )
                        },
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    # Total reorder summary
                    total_reorder = store_items['Recommended_Order'].astype(str).str.replace(' pcs', '').astype(float).sum()
                    st.info(f"**Total Recommended Order for {store}: {int(total_reorder):,} units across {len(store_items)} SKUs**")
        else:
            st.success("🎉 No critical items found! All stock levels are within acceptable ranges.")
    
    with tab4:
        st.markdown("### 📈 Trends & Category Analysis")
        
        # Sales trend analysis
        if not sales_filtered.empty:
            # Monthly sales trend
            sales_filtered['Month'] = sales_filtered['Orderdate'].dt.to_period('M')
            monthly_sales = sales_filtered.groupby('Month').agg({
                'ItemOrdered': 'sum',
                'ItemPrice': lambda x: (x * sales_filtered.loc[x.index, 'ItemOrdered']).sum() / sales_filtered.loc[x.index, 'ItemOrdered'].sum()
            }).reset_index()
            
            monthly_sales['Month'] = monthly_sales['Month'].dt.to_timestamp()
            monthly_sales['Revenue'] = monthly_sales['ItemOrdered'] * monthly_sales['ItemPrice']
            
            # Plot trend
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            
            fig.add_trace(
                go.Scatter(x=monthly_sales['Month'], y=monthly_sales['ItemOrdered'],
                          name="Units Sold", line=dict(color='#3B82F6', width=3)),
                secondary_y=False,
            )
            
            fig.add_trace(
                go.Bar(x=monthly_sales['Month'], y=monthly_sales['Revenue'],
                      name="Revenue", marker_color='#10B981', opacity=0.6),
                secondary_y=True,
            )
            
            fig.update_layout(
                title="Monthly Sales Trend",
                hovermode="x unified",
                height=400
            )
            
            fig.update_yaxes(title_text="Units Sold", secondary_y=False)
            fig.update_yaxes(title_text="Revenue (Rp)", secondary_y=True)
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Category performance analysis
            st.markdown("#### Category Performance Analysis")
            
            if 'SKU_Category' in analysis_df.columns:
                # Heatmap: Store vs Category Performance
                pivot_data = analysis_df.pivot_table(
                    index='Store_Name',
                    columns='SKU_Category',
                    values='Stock_Value',
                    aggfunc='sum',
                    fill_value=0
                )
                
                if not pivot_data.empty:
                    fig_heat = px.imshow(pivot_data,
                                       labels=dict(x="Category", y="Store", color="Stock Value"),
                                       title="Stock Value Distribution (Store × Category)",
                                       color_continuous_scale='Blues')
                    fig_heat.update_layout(height=400)
                    st.plotly_chart(fig_heat, use_container_width=True)
    
    # --- FOOTER DAN DOWNLOAD ---
    st.markdown("---")
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        st.caption(f"Dashboard updated: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} | Data source: Google Sheets")
    
    with col2:
        if not analysis_df.empty:
            csv = analysis_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Download Full Report",
                csv,
                f"flagship_inventory_report_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                "text/csv",
                use_container_width=True
            )
    
    with col3:
        if len(inventory_tables) > 0:
            # Buat summary report untuk inventory control
            summary_report = []
            for table in inventory_tables:
                summary_report.append({
                    'Date': datetime.now().strftime('%d/%m/%Y'),
                    'Store': table['store_name'],
                    'Ideal_Stock': table['raw_metrics']['ideal_stock'],
                    'Need_Replenishment': table['raw_metrics']['need_replenishment'],
                    'Over_Stock': table['raw_metrics']['over_stock'],
                    'Non_Moving_Stock': table['raw_metrics']['non_moving'],
                    'Count_of_SKU': table['raw_metrics']['count_of_sku'],
                    'Qty_Stock': table['raw_metrics']['qty_stock'],
                    'AVG_Sales': table['raw_metrics']['avg_sales'],
                    'Replenishment_Qty_Suggest': table['raw_metrics']['replenishment_qty_suggest'],
                    'Weekcover': table['raw_metrics']['weekcover']
                })
            
            summary_df = pd.DataFrame(summary_report)
            csv_summary = summary_df.to_csv(index=False).encode('utf-8')
            
            st.download_button(
                "📋 Inventory Control",
                csv_summary,
                f"inventory_control_summary_{datetime.now().strftime('%Y%m%d')}.csv",
                "text/csv",
                use_container_width=True
            )

except Exception as e:
    st.error(f"❌ An error occurred: {str(e)}")
    
    # Debug information (collapsed)
    with st.expander("⚠️ Technical Details (for debugging)"):
        import traceback
        st.code(traceback.format_exc())
