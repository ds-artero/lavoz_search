import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
from urllib.parse import urljoin
from collections import defaultdict, OrderedDict
import plotly.express as px 
import re
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import io

# --- Configuration and Core Scraping Functions ---

DOMAIN = "https://www.lavozdegalicia.es"
SEARCH_ENDPOINT = "https://www.lavozdegalicia.es/buscador/q/"
DEFAULT_PAGE_SIZE = 10

# --- Helper: Name Variations ---
def get_search_variations(name_input):
    """
    Generates variations of a name.
    Input: "CLAUDIA ZAPATER"
    Output: ["CLAUDIA ZAPATER", "C. ZAPATER", "ZAPATER"]
    """
    name_input = name_input.strip()
    variations = [name_input] # Always include the original
    
    # Split by whitespace
    parts = name_input.split()
    
    # Only generate variations if we have at least 2 names (First + Last)
    if len(parts) >= 2:
        first_name = parts[0]
        # Join the rest in case of compound surnames
        surname = " ".join(parts[1:]) 
        
        # Variation 1: Initial + Surname (e.g., "C. ZAPATER")
        initial_var = f"{first_name[0]}. {surname}"
        if initial_var not in variations:
            variations.append(initial_var)
            
        # Variation 2: Surname only (e.g., "ZAPATER")
        if surname not in variations:
            variations.append(surname)
            
    return variations

# --- Helper: Fiscal Month Calculator ---
def calculate_fiscal_month(date_obj):
    """
    Determines the 'Fiscal Month' (YYYY-MM) based on the 16th-15th rule.
    If date is > 15th, it belongs to the NEXT month.
    """
    try:
        if pd.isna(date_obj):
            return None
            
        if date_obj.day > 15:
            # Belongs to next month
            adjusted_date = date_obj + relativedelta(months=1)
        else:
            # Belongs to current month
            adjusted_date = date_obj
            
        return adjusted_date.strftime('%Y-%m')
    except:
        return None

# --- Date Parsing Helper ---
@st.cache_data
def parse_date_and_normalize(date_str):
    """Parses Spanish date strings (e.g., '18 de julio de 2025') into YYYY-MM-DD."""
    date_str = date_str.strip()
    spanish_months = {
        'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
        'julio': 7, 'agosto': 8, 'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12
    }
    match = re.search(r'(\d+)\s+de\s+(\w+)\s+de\s+(\d{4})', date_str, re.IGNORECASE)
    if match:
        try:
            day = int(match.group(1))
            month_name = match.group(2).lower()
            year = int(match.group(3))
            month_num = spanish_months.get(month_name)
            if month_num:
                return f"{year}-{month_num:02d}-{day:02d}"
        except Exception:
            pass
            
    # Fallback for relative dates
    if any(keyword in date_str.lower() for keyword in ['hoy', 'ayer', 'hora', 'minuto']):
        return datetime.now().strftime('%Y-%m-%d')
            
    return date_str

# --- Data Summarization and Plotting ---

@st.cache_data
def summarize_by_group(df):
    """
    Summarizes the count by the pre-calculated MONTH_GROUP column.
    """
    if df.empty or 'MONTH_GROUP' not in df.columns:
        return pd.DataFrame({'Month': [], 'Count': []})
            
    monthly_counts = df['MONTH_GROUP'].value_counts().sort_index()
    
    summary_df = pd.DataFrame({'Month': monthly_counts.index, 'Count': monthly_counts.values})
    return summary_df

@st.cache_data
def create_monthly_plot_plotly(summary_df, search_term):
    if summary_df.empty:
        return None
    
    average_count = summary_df['Count'].mean()
        
    fig = px.bar(
        summary_df,
        x='Month',
        y='Count',
        text='Count',
        title=f"Artículos Publicados por Período Mensual (Búsqueda: {search_term})",
        labels={
            "Count": "Número de Artículos Únicos",
            "Month": "Mes/Año (Periodo: 16-15)"
        },
        color_discrete_sequence=['#0079c1']
    )
    
    fig.add_hline(
        y=average_count,
        line_dash="dot",
        line_color="#d9534f",
        annotation_text=f"Media: {average_count:.2f}",
        annotation_position="top right",
        annotation_font_color="#d9534f"
    )
    
    fig.update_traces(
        textposition='outside',
        marker_line_color='rgb(8,48,107)', 
        marker_line_width=1.5, 
        opacity=0.9
    )
    
    fig.update_layout(
        xaxis={'categoryorder':'category ascending'},
        hovermode="x unified",
        template="plotly_white",
        yaxis_title="Número de Artículos",
        height=550
    )
    
    return fig

# --- Main Scraping Logic ---

# --- Main Scraping Logic ---

def scrape_lavoz_recursive(search_variations, max_page=5, page_size=DEFAULT_PAGE_SIZE, progress_bar=None, status_text=None):
    """
    Scrapes articles for a LIST of search terms, removing duplicates.
    Includes strict encoding fixes for Spanish characters.
    """
    all_articles_data = []
    unique_links = set() 
    
    base_form_data = {
        'pageSize': str(page_size),
        'sort': 'D0003_FECHAPUBLICACION desc',
        'doctype': '', 'dateFrom': '', 'dateTo': '', 'edicion': '',
        'formato': '', 'seccion': '', 'blog': '', 'autor': '',
        'source': 'info',
    }
    
    total_steps = len(search_variations) * max_page
    current_step = 0

    for term in search_variations:
        base_form_data['text'] = term 
        
        if status_text:
            status_text.markdown(f"🔎 Buscando variante: **'{term}'**...")

        for page_num in range(1, max_page + 1):
            current_step += 1
            if progress_bar:
                progress_bar.progress(current_step / total_steps)

            form_data = base_form_data.copy()
            form_data['pageNumber'] = str(page_num) 

            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Referer': SEARCH_ENDPOINT 
                }
                response = requests.post(SEARCH_ENDPOINT, headers=headers, data=form_data, timeout=10)
                
                # --- ENCODING FIX EXPLANATION ---
                # 1. We explicitly tell requests that the content is UTF-8.
                response.encoding = 'utf-8' 
                
                # 2. We pass response.text (which uses the encoding above) to BS4.
                # IMPORTANT: Do not pass response.content, or BS4 will try to guess the encoding and fail again.
                soup = BeautifulSoup(response.text, 'html.parser')
                
                article_containers = soup.select('article') 
                
                if not article_containers:
                    break
                    
                for container in article_containers:
                    link_tag = container.select_one('h1 a[href]')
                    if not (link_tag and link_tag.get('href')):
                        continue 
                    
                    article_url = urljoin(DOMAIN, link_tag.get('href'))
                    
                    if article_url in unique_links:
                        continue

                    # Double check cleaning just in case
                    title = link_tag.get_text(strip=True)
                    
                    # Date parsing
                    date_tag = container.select_one('time.entry-date')
                    date_raw = date_tag.get_text(strip=True) if date_tag else 'Date Not Found'
                    
                    # Sometimes the date is inside the datetime attribute, sometimes in text
                    if date_tag and date_tag.has_attr('datetime'):
                         date_raw_attr = date_tag['datetime']
                         # Prefer the attribute if it looks like a full date, otherwise use text
                         if len(date_raw_attr) > 5: 
                             date_raw = date_raw_attr

                    normalized_date = parse_date_and_normalize(date_raw)

                    unique_links.add(article_url)
                    all_articles_data.append({
                        'TITLE': title,
                        'DATE_NORMALIZED': normalized_date,
                        'DATE_RAW': date_raw,
                        'URL': article_url,
                        'FOUND_VIA': term 
                    })
            
                time.sleep(0.5) 

            except requests.exceptions.RequestException as e:
                st.error(f"Error fetching data: {e}")
                break
        
    return pd.DataFrame(all_articles_data)

# --- Streamlit Application Layout ---

st.set_page_config(layout="wide", page_title="La Voz de Galicia Search Scraper")

st.title("📰 Monitor de Prensa - La Voz de Galicia" )
st.markdown("""
Busca un nombre y el sistema buscará automáticamente variantes (Ej: Nombre Apellido, N. Apellido, Apellido).
**Los meses están calculados como un período fiscal: 16-15 del siguiente mes.**
""")

# --- Sidebar ---
st.sidebar.header("🔍 Configuración")
search_input = st.sidebar.text_input("NOMBRE O TÉRMINO A BUSCAR", value="CLAUDIA ZAPATER")
max_pages = st.sidebar.slider("Páginas máx. por variante", 1, 10, 5)

# --- Search Logic ---
if 'df_results' not in st.session_state:
    st.session_state['df_results'] = pd.DataFrame()

if st.sidebar.button("🔍 Buscar", type="primary"):
    
    # 1. Generate Variations
    variations = get_search_variations(search_input)
    
    st.header("⏳ Procesando Búsqueda Inteligente...")
    st.info(f"Buscando las siguientes variantes: {', '.join([f'**{v}**' for v in variations])}")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 2. Run Scraper
    df_results_new = scrape_lavoz_recursive(
        variations, 
        max_pages, 
        progress_bar=progress_bar, 
        status_text=status_text
    )
    
    st.session_state['df_results'] = df_results_new
    
    progress_bar.empty()
    status_text.success(f"✅ Completado. Encontrados {len(st.session_state['df_results'])} artículos únicos.")

# --- Results Display ---
df_results = st.session_state['df_results']

if not df_results.empty:
    
    # 1. Pre-processing: Date & Fiscal Month
    df_results['DATE_OBJ'] = pd.to_datetime(df_results['DATE_NORMALIZED'], errors='coerce')
    df_results.dropna(subset=['DATE_OBJ'], inplace=True)
    
    # Calculate the Fiscal Month Column
    df_results['MONTH_GROUP'] = df_results['DATE_OBJ'].apply(calculate_fiscal_month)
    
    # --- FILTERS ---
    st.sidebar.markdown("---")
    st.sidebar.subheader("📅 Filtros")
    
    # Date Range Filter
    min_date = df_results['DATE_OBJ'].min().date()
    max_date = df_results['DATE_OBJ'].max().date()
    
    date_range = st.sidebar.date_input(
        "Rango de Fechas",
        [min_date, max_date],
        min_value=min_date,
        max_value=max_date
    )
    
    # Group Month Filter (New)
    available_months = sorted(df_results['MONTH_GROUP'].dropna().unique(), reverse=True)
    selected_months = st.sidebar.multiselect(
        "Filtrar por Mes Fiscal (Grupo)",
        options=available_months,
        default=available_months
    )
    
    # Apply Filters
    mask = pd.Series(True, index=df_results.index)
    
    # Filter by Date Range
    if len(date_range) == 2:
        start_date, end_date = sorted(date_range)
        end_date_time = pd.to_datetime(end_date) + timedelta(days=1) - timedelta(seconds=1)
        mask = mask & (df_results['DATE_OBJ'] >= pd.to_datetime(start_date)) & (df_results['DATE_OBJ'] <= end_date_time)
        
    # Filter by Month Group
    if selected_months:
        mask = mask & (df_results['MONTH_GROUP'].isin(selected_months))
        
    df_filtered = df_results[mask].copy()

    if df_filtered.empty:
        st.warning("No hay resultados con los filtros actuales.")
    else:
        # --- Section 1: Data Table ---
        st.subheader(f"📊 Listado Detallado ({len(df_filtered)} Artículos)")
        
        # Define column order including the new MONTH_GROUP
        display_cols = ['TITLE', 'DATE_NORMALIZED', 'MONTH_GROUP', 'URL']
        
        st.dataframe(
            df_filtered[display_cols], 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "URL": st.column_config.LinkColumn("Link"),
                "MONTH_GROUP": st.column_config.TextColumn("Mes Fiscal (16-15)")
            }
        )

        # --- Section 2: Summary Table ---
        summary_df = summarize_by_group(df_filtered)
        
        col_summ_1, col_summ_2 = st.columns([1, 2])
        
        with col_summ_1:
            st.subheader("🗓️ Resumen Tabla")
            st.dataframe(
                summary_df.sort_values(by='Month', ascending=False), 
                use_container_width=True, 
                hide_index=True
            )
            
        with col_summ_2:
             # --- Section 3: Visualization ---
            st.subheader("📈 Gráfico Mensual")
            fig_plotly = create_monthly_plot_plotly(summary_df, search_input)
            if fig_plotly:
                st.plotly_chart(fig_plotly, use_container_width=True)

        # --- Section 4: Download ---
        st.subheader("⬇️ Descargar Datos")
        csv_buffer = io.StringIO()
        df_filtered.to_csv(csv_buffer, index=False)
        st.download_button(
            label="Descargar CSV Filtrado",
            data=csv_buffer.getvalue(),
            file_name=f'lavoz_report_{search_input.replace(" ", "_")}.csv',
            mime='text/csv'
        )
        
else:
    st.info("Utiliza el panel lateral para iniciar una búsqueda.")
