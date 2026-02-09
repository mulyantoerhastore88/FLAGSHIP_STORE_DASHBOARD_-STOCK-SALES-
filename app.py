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
    .status-badge {
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
        display: inline-block;
    }
    .category-badge {
        padding: 0.2rem 0.6rem;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 500;
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
    .tab-container {
        background: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        margin-top: 1rem;
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
        
        # Sheet 1: Store Kamus
        ws_store_kamus = sh_kamus.get_worksheet(0)
        df_store_kamus = pd.DataFrame(ws_store_kamus.get_all_records())
        
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
    
    # Klasifikasi Status
    def classify_status(row):
        if row['Total'] > 0 and row['AMS'] == 0:
            return "📦 New/Dead Stock"
        elif row['Month_Cover'] < 0.5:
            return "🚨 Critical"
        elif row['Month_Cover'] < 1:
            return "⚠️ Need Reorder"
        elif row['Month_Cover'] <= 1.5:
            return "✅ Healthy"
        elif row['Month_Cover'] <= 3:
            return "📈 Good Buffer"
        else:
            return "🛑 Overstock"
    
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
        <h1 style="color: white; margin: 0; font-size: 2.8rem;">🏭 Supply Chain Command Center</h1>
        <p style="opacity: 0.9; font-size: 1.1rem; margin-top: 0.5rem;">Flagship Store Inventory & Replenishment Dashboard</p>
        <p style="opacity: 0.8; font-size: 0.9rem; margin-top: 0.2rem;">SKU Filter Active: Only SKUs from SKU Kamus are displayed</p>
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
    
    # Mapping store code
    df_sales['POS_Code'] = df_sales['Ordernumber'].astype(str).str[:4]
    df_sales_mapped = pd.merge(df_sales, df_store_kamus, left_on='POS_Code', right_on='POS', how='left')
    
    # --- SIDEBAR FILTER PROFESIONAL ---
    with st.sidebar:
        st.markdown("### ⚙️ Dashboard Configuration")
        
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
        store_options = ["All Stores"] + sorted(df_stock['Store_Name'].dropna().unique().tolist())
        selected_stores = st.multiselect(
            "Select Stores:",
            options=store_options[1:],
            default=store_options[1:] if len(store_options) > 1 else []
        )
        
        if not selected_stores:
            selected_stores = store_options[1:]
        
        # Status Filter
        st.markdown("**📈 Stock Status Filter**")
        status_options = ["🚨 Critical", "⚠️ Need Reorder", "✅ Healthy", "📈 Good Buffer", "🛑 Overstock", "📦 New/Dead Stock"]
        selected_status = st.multiselect(
            "Show statuses:",
            options=status_options,
            default=status_options
        )
        
        # Threshold Settings
        st.markdown("**⚡ Alert Thresholds**")
        reorder_threshold = st.slider("Reorder Threshold (months)", 0.5, 2.0, 1.0, 0.1)
        overstock_threshold = st.slider("Overstock Threshold (months)", 2.0, 6.0, 3.0, 0.5)
    
    # Filter SKU Kamus berdasarkan kategori yang dipilih
    df_sku_kamus_filtered = df_sku_kamus[df_sku_kamus['SKU_Category'].isin(selected_categories)] if selected_categories else df_sku_kamus
    
    # Filter data berdasarkan pilihan store
    stock_filtered = df_stock[df_stock['Store_Name'].isin(selected_stores)] if selected_stores else df_stock
    sales_filtered = df_sales_mapped[df_sales_mapped['Store_Name'].isin(selected_stores)] if selected_stores else df_sales_mapped
    
    # --- KPI CARDS ---
    st.markdown("### 📈 Executive Summary")
    
    # Hitung metrics utama dengan filter SKU
    analysis_df = calculate_stock_health(stock_filtered, sales_filtered, df_sku_kamus_filtered)
    
    if not analysis_df.empty:
        total_stock_value = analysis_df['Stock_Value'].sum()
        total_skus = analysis_df['SKU'].nunique()
        total_units = analysis_df['Total'].sum()
        
        # Hitung distribusi status
        status_counts = analysis_df['Status'].value_counts()
        critical_count = status_counts.get("🚨 Critical", 0)
        reorder_count = status_counts.get("⚠️ Need Reorder", 0)
        healthy_count = status_counts.get("✅ Healthy", 0) + status_counts.get("📈 Good Buffer", 0)
        
        total_items = status_counts.sum()
        health_percentage = (healthy_count / total_items * 100) if total_items > 0 else 0
        
        # Display KPI Cards
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">Total Stock Value</div>
                <div class="metric-value">Rp {total_stock_value:,.0f}</div>
                <div class="metric-change">{total_skus} SKUs | {len(selected_categories)} Categories</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">Stock Health Score</div>
                <div class="metric-value">{health_percentage:.1f}%</div>
                <div class="metric-change">{healthy_count} of {total_items} SKUs</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">Require Attention</div>
                <div class="metric-value">{critical_count + reorder_count}</div>
                <div class="metric-change">SKUs Need Action</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col4:
            avg_cover = analysis_df[analysis_df['Month_Cover'] < 50]['Month_Cover'].median()
            avg_cover = 0 if pd.isna(avg_cover) else avg_cover
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">Avg. Month Cover</div>
                <div class="metric-value">{avg_cover:.1f}x</div>
                <div class="metric-change">{total_units:,} Total Units</div>
            </div>
            """, unsafe_allow_html=True)
        
        # Category Distribution
        st.markdown("#### 📊 Category Distribution")
        category_cols = st.columns(min(4, len(selected_categories)))
        
        for idx, category in enumerate(selected_categories):
            if idx < 4:  # Tampilkan maksimal 4 kategori di baris pertama
                cat_data = analysis_df[analysis_df['SKU_Category'] == category]
                with category_cols[idx]:
                    cat_skus = len(cat_data)
                    cat_units = cat_data['Total'].sum()
                    cat_value = cat_data['Stock_Value'].sum()
                    
                    st.markdown(f"""
                    <div style="background: #f8f9fa; padding: 1rem; border-radius: 10px; border-left: 4px solid #3B82F6;">
                        <div style="font-weight: 600; font-size: 0.9rem; margin-bottom: 0.5rem;">{category}</div>
                        <div style="display: flex; justify-content: space-between;">
                            <span style="font-size: 0.8rem; opacity: 0.7;">SKUs:</span>
                            <span style="font-weight: 700;">{cat_skus}</span>
                        </div>
                        <div style="display: flex; justify-content: space-between;">
                            <span style="font-size: 0.8rem; opacity: 0.7;">Units:</span>
                            <span style="font-weight: 700;">{cat_units:,}</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-top: 0.5rem;">
                            <span style="font-size: 0.8rem; opacity: 0.7;">Value:</span>
                            <span style="font-weight: 700;">Rp {cat_value:,.0f}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
    
    # --- TABBED INTERFACE ---
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Store Overview", "🚨 Priority Actions", "📦 Stock Analysis", "📈 Trends by Category"])
    
    with tab1:
        st.markdown("### 🏪 Store Performance Summary")
        
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
                            <div style="font-size: 0.8rem; opacity: 0.7;">Avg. Cover:</div>
                            <div style="font-weight: 700; font-size: 1.2rem;">{row['Avg Month Cover']:.1f}x</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
            
            # Store comparison chart
            st.markdown("#### Store Comparison by Category")
            
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
    
    with tab2:
        st.markdown("### 🚨 Priority Action Items")
        
        # Filter SKUs yang butuh perhatian
        priority_items = analysis_df[analysis_df['Status'].isin(['🚨 Critical', '⚠️ Need Reorder'])]
        
        if not priority_items.empty:
            # Group by category untuk analisis
            st.markdown("#### Action Items by Category")
            
            for category in priority_items['SKU_Category'].unique():
                cat_items = priority_items[priority_items['SKU_Category'] == category]
                
                with st.expander(f"**{category}** - {len(cat_items)} SKUs Need Attention", expanded=True):
                    # Calculate recommended order quantity
                    cat_items = cat_items.copy()
                    cat_items['Recommended_Order'] = np.where(
                        cat_items['Month_Cover'] < 1,
                        (cat_items['AMS'] * 1.5 - cat_items['Total']).clip(lower=1),
                        (cat_items['AMS'] * 0.5).clip(lower=1)
                    )
                    
                    # Display table grouped by store
                    for store in cat_items['Store_Name'].unique():
                        store_items = cat_items[cat_items['Store_Name'] == store]
                        
                        st.markdown(f"**Store: {store}**")
                        display_cols = ['SKU', 'Total', 'AMS', 'Month_Cover', 'Recommended_Order', 'Status']
                        styled_df = store_items[display_cols].sort_values('Month_Cover')
                        
                        # Format untuk display
                        styled_df['Month_Cover'] = styled_df['Month_Cover'].apply(lambda x: f"{x:.1f}x")
                        styled_df['Recommended_Order'] = styled_df['Recommended_Order'].apply(lambda x: f"{int(x)} pcs")
                        styled_df['AMS'] = styled_df['AMS'].apply(lambda x: f"{x:.1f}/month")
                        
                        st.dataframe(
                            styled_df,
                            column_config={
                                "Status": st.column_config.TextColumn(
                                    width="small",
                                    help="Stock status classification"
                                )
                            },
                            use_container_width=True,
                            hide_index=True
                        )
                        
                        # Total reorder summary per store-category
                        total_reorder = store_items['Recommended_Order'].sum()
                        st.info(f"**Total recommended order for {store} ({category}): {int(total_reorder):,} units**")
        else:
            st.success("🎉 No critical items found! All stock levels are within acceptable ranges.")
    
    with tab3:
        st.markdown("### 📦 Detailed Stock Analysis by Category")
        
        # Pilih kategori untuk detail view
        selected_detail_category = st.selectbox(
            "Select Category for Detailed View:",
            options=selected_categories
        )
        
        if selected_detail_category:
            category_data = analysis_df[analysis_df['SKU_Category'] == selected_detail_category]
            
            if not category_data.empty:
                # Metrics untuk kategori ini
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("SKUs in Category", len(category_data))
                with col2:
                    st.metric("Total Units", f"{category_data['Total'].sum():,}")
                with col3:
                    st.metric("Stock Value", f"Rp {category_data['Stock_Value'].sum():,.0f}")
                with col4:
                    avg_cover = category_data['Month_Cover'].median()
                    st.metric("Median Cover", f"{avg_cover:.1f}x")
                
                # Interactive data table dengan grouping per store
                for store in category_data['Store_Name'].unique():
                    store_cat_data = category_data[category_data['Store_Name'] == store]
                    
                    with st.expander(f"**{store}** - {len(store_cat_data)} SKUs", expanded=True):
                        st.dataframe(
                            store_cat_data[['SKU', 'Status', 'Total', 'AMS', 'Month_Cover', 'Stock_Value']].sort_values('Month_Cover'),
                            column_config={
                                "Status": st.column_config.SelectboxColumn(
                                    "Status",
                                    help="Current stock status",
                                    width="small",
                                    options=status_options
                                ),
                                "Month_Cover": st.column_config.ProgressColumn(
                                    "Month Cover",
                                    help="Current stock divided by monthly sales",
                                    format="%.1fx",
                                    min_value=0,
                                    max_value=10
                                ),
                                "Stock_Value": st.column_config.NumberColumn(
                                    "Value (Rp)",
                                    format="Rp %.0f"
                                )
                            },
                            use_container_width=True,
                            height=300
                        )
    
    with tab4:
        st.markdown("### 📈 Category Performance Trends")
        
        # Sales trend analysis per kategori
        if not sales_filtered.empty and 'SKU_Category' in sales_filtered.columns:
            # Filter sales hanya untuk SKU yang ada di kamus
            sales_cat_filtered = filter_by_sku_kamus(sales_filtered, df_sku_kamus_filtered)
            
            if not sales_cat_filtered.empty:
                # Monthly sales trend per category
                sales_cat_filtered['Month'] = sales_cat_filtered['Orderdate'].dt.to_period('M')
                monthly_sales_cat = sales_cat_filtered.groupby(['Month', 'SKU_Category']).agg({
                    'ItemOrdered': 'sum',
                    'ItemPrice': lambda x: (x * sales_cat_filtered.loc[x.index, 'ItemOrdered']).sum() / sales_cat_filtered.loc[x.index, 'ItemOrdered'].sum()
                }).reset_index()
                
                monthly_sales_cat['Month'] = monthly_sales_cat['Month'].dt.to_timestamp()
                monthly_sales_cat['Revenue'] = monthly_sales_cat['ItemOrdered'] * monthly_sales_cat['ItemPrice']
                
                # Plot trend per category
                fig = px.line(monthly_sales_cat, x='Month', y='ItemOrdered',
                            color='SKU_Category',
                            title='Monthly Sales Trend by Category',
                            markers=True)
                fig.update_layout(height=400, hovermode="x unified")
                st.plotly_chart(fig, use_container_width=True)
                
                # Category comparison bar chart
                st.markdown("#### 📊 Current Stock Analysis by Category")
                
                # Bar chart: Stock Cover by Category
                fig2 = px.box(analysis_df, x='SKU_Category', y='Month_Cover',
                            title='Stock Cover Distribution by Category',
                            color='SKU_Category')
                fig2.update_layout(height=400, showlegend=False)
                fig2.update_yaxes(title_text="Month Cover")
                st.plotly_chart(fig2, use_container_width=True)
                
                # Heatmap: Status Distribution by Category
                status_by_category = analysis_df.groupby(['SKU_Category', 'Status']).size().unstack(fill_value=0)
                
                if not status_by_category.empty:
                    fig3 = px.imshow(status_by_category.T,
                                   labels=dict(x="Category", y="Status", color="Count"),
                                   title="Status Distribution by Category",
                                   color_continuous_scale='RdYlGn')
                    fig3.update_layout(height=400)
                    st.plotly_chart(fig3, use_container_width=True)
    
    # --- FOOTER DAN DOWNLOAD ---
    st.markdown("---")
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        st.caption(f"Dashboard updated: {datetime.now().strftime('%d %b %Y %H:%M:%S')} | Showing {len(analysis_df)} SKUs from {len(selected_categories)} categories")
    
    with col2:
        if not analysis_df.empty:
            csv = analysis_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Download Full Report",
                csv,
                f"supply_chain_report_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                "text/csv",
                use_container_width=True
            )
    
    with col3:
        if not df_sku_kamus_filtered.empty:
            csv_kamus = df_sku_kamus_filtered.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📋 SKU Kamus",
                csv_kamus,
                f"sku_kamus_filtered_{datetime.now().strftime('%Y%m%d')}.csv",
                "text/csv",
                use_container_width=True
            )

except Exception as e:
    st.error(f"❌ An error occurred: {str(e)}")
    
    # Debug information (collapsed)
    with st.expander("⚠️ Technical Details (for debugging)"):
        import traceback
        st.code(traceback.format_exc())
