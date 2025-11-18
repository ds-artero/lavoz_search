import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
from urllib.parse import urljoin
from collections import defaultdict, OrderedDict
# Cambiamos plt por px y quitamos las dependencias de PDF (Matplotlib y PdfPages)
import plotly.express as px 
import re
from datetime import datetime, date, timedelta # Importado timedelta para el filtro de fecha
from dateutil.relativedelta import relativedelta
import io # Necesario para la descarga CSV

# --- Configuration and Core Scraping Functions ---

DOMAIN = "https://www.lavozdegalicia.es"
SEARCH_ENDPOINT = "https://www.lavozdegalicia.es/buscador/q/"
DEFAULT_PAGE_SIZE = 10

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
            
    # Fallback for relative dates (we use today's date)
    if any(keyword in date_str.lower() for keyword in ['hoy', 'ayer', 'hora', 'minuto']):
        return datetime.now().strftime('%Y-%m-%d')
            
    return date_str

# --- Data Summarization and Plotting ---

@st.cache_data
def summarize_by_month(df):
    """
    Processes DataFrame and summarizes the count by YYYY-MM, 
    where a month runs from the 16th to the 15th of the next month.
    """
    if df.empty:
        return pd.DataFrame({'Month': [], 'Count': []})
            
    monthly_counts = defaultdict(int)
    
    for date_str in df['DATE_NORMALIZED']:
        if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                
                # --- NEW LOGIC: 16th to 15th Period ---
                if date_obj.day > 15:
                    # If date is 16th or later, it belongs to the NEXT month's period
                    # Use relativedelta to reliably add one month, handling year end
                    adjusted_date = date_obj + relativedelta(months=1)
                else:
                    # If date is 15th or earlier, it belongs to the CURRENT month's period
                    adjusted_date = date_obj
                
                # The month key is based on the ADJUSTED month (the month the period is named after)
                month_key = adjusted_date.strftime('%Y-%m')
                monthly_counts[month_key] += 1
                
            except ValueError:
                # Handle cases where DATE_NORMALIZED is not a valid date string
                pass

    sorted_items = OrderedDict(sorted(monthly_counts.items()))
    
    summary_df = pd.DataFrame(list(sorted_items.items()), columns=['Month', 'Count'])
    return summary_df

# Nueva función de Plotting con Plotly Express
@st.cache_data
def create_monthly_plot_plotly(summary_df, search_term):
    """Creates a Plotly bar chart of article count vs. month/year, including the average."""
    if summary_df.empty:
        return None # Devuelve None si no hay datos
    
    # Calcular el promedio de artículos por mes
    average_count = summary_df['Count'].mean()
        
    fig = px.bar(
        summary_df,
        x='Month',
        y='Count',
        text='Count',
        title=f"Artículos Publicados por Período Mensual para: '{search_term}'",
        labels={
            "Count": "Número de Artículos Únicos",
            "Month": "Mes/Año (Periodo: 16-15 del siguiente)"
        },
        color_discrete_sequence=['#0079c1']
    )
    
    # Añadir la línea de promedio
    fig.add_hline(
        y=average_count,
        line_dash="dot",
        line_color="#d9534f", # Rojo para destacar
        annotation_text=f"Media: {average_count:.2f} artículos/mes",
        annotation_position="top right",
        annotation_font_color="#d9534f"
    )
    
    # Ajustes estéticos para un look más moderno
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
        yaxis_title="Número de Artículos Únicos",
        height=550
    )
    
    return fig

# Se han eliminado las funciones create_monthly_plot_matplotlib y generate_pdf_report.

# --- Main Scraping Logic (Adapted for Streamlit) ---

def scrape_lavoz_main_search_post(search_text, max_page=5, page_size=DEFAULT_PAGE_SIZE, progress_bar=None, status_text=None):
    """
    Scrapes articles from the main La Voz de Galicia search page using POST requests.
    """
    all_articles_data = []
    unique_links = set() 
    
    base_form_data = {
        'text': search_text,
        'pageSize': str(page_size),
        'sort': 'D0003_FECHAPUBLICACION desc',
        'doctype': '', 'dateFrom': '', 'dateTo': '', 'edicion': '',
        'formato': '', 'seccion': '', 'blog': '', 'autor': '',
        'source': 'info',
    }
    
    articles_found = 0

    for page_num in range(1, max_page + 1):
        
        if status_text:
            status_text.text(f"Fetching page {page_num}/{max_page}...")

        form_data = base_form_data.copy()
        form_data['pageNumber'] = str(page_num) 

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Referer': SEARCH_ENDPOINT 
            }
            response = requests.post(SEARCH_ENDPOINT, headers=headers, data=form_data, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            
            article_containers = soup.select('article') 
            
            if not article_containers:
                break
                
            for container in article_containers:
                
                link_tag = container.select_one('h1 a[href]')
                if not (link_tag and link_tag.get('href')):
                    continue 
                
                article_url = urljoin(DOMAIN, link_tag.get('href'))
                title = link_tag.get_text(strip=True)
                
                date_tag = container.select_one('time.entry-date')
                date_raw = date_tag.get('datetime', 'Date Not Found') if date_tag else 'Date Not Found'
                normalized_date = parse_date_and_normalize(date_raw)

                if article_url not in unique_links:
                    unique_links.add(article_url)
                    all_articles_data.append({
                        'TITLE': title,
                        'DATE_NORMALIZED': normalized_date,
                        'DATE_RAW': date_raw,
                        'URL': article_url,
                    })
                    articles_found += 1
            
            time.sleep(1.0) # Be polite

        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching page {page_num}: {e}")
            break
            
        if progress_bar:
             progress_bar.progress(page_num / max_page)
        
    return pd.DataFrame(all_articles_data)


# --- Streamlit Application Layout ---

st.set_page_config(layout="wide", page_title="La Voz de Galicia Search Scraper")

st.title("📰 Resumen de tus Artículos en La Voz de Galicia" )
st.markdown("Busca un término y obtén un resumen de la frecuencia de publicación. **Los meses están calculados como un período fiscal: 16-15 del siguiente mes. Ej: Octubre (16 Oct - 15 Nov).**")

st.sidebar.header("🔍 Search Configuration")
search_term = st.sidebar.text_input("NOMBRE O TÉRMINO A BUSCAR", value="CLAUDIA ZAPATER")
max_pages = st.sidebar.slider("Maximum Pages to Scan (10 items/page)", 1, 30, 10)

# Inicializar un DataFrame vacío en el estado de la sesión si no existe
if 'df_results' not in st.session_state:
    st.session_state['df_results'] = pd.DataFrame()

# CAmbio aquí: "Run Scraper" a "🔍 Buscar"
if st.sidebar.button("🔍 Buscar", type="primary"):
    
    # CAmbio aquí: "Scraping Results" a "Buscando..."
    st.header("⏳ Buscando...")
    st.info(f"Buscando: **{search_term}** a través de **{max_pages}** páginas...")
    
    # Placeholders for live progress
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # Run the scraper
    df_results_new = scrape_lavoz_main_search_post(
        search_term, 
        max_pages, 
        progress_bar=progress_bar, 
        status_text=status_text
    )
    
    st.session_state['df_results'] = df_results_new
    
    progress_bar.empty()
    status_text.success(f"✅ Scraping completado. Encontrados {len(st.session_state['df_results'])} artículos únicos.")

# Usamos el DataFrame de la sesión
df_results = st.session_state['df_results']

if not df_results.empty:
    
    # 1. Preparar el DataFrame para la filtración de fechas
    # Convertir 'DATE_NORMALIZED' a datetime para poder filtrar
    df_results['DATE_OBJ'] = pd.to_datetime(df_results['DATE_NORMALIZED'], errors='coerce')
    df_results.dropna(subset=['DATE_OBJ'], inplace=True) # Eliminar filas con fechas no válidas
    
    min_date_available = df_results['DATE_OBJ'].min().date()
    max_date_available = df_results['DATE_OBJ'].max().date()
    
    # --- FILTRO DE FECHAS APLICADO AQUÍ ---
    st.sidebar.subheader("📅 Filtrado Temporal")
    date_range = st.sidebar.date_input(
        "Rango de Fechas de Publicación",
        [min_date_available, max_date_available],
        min_value=min_date_available,
        max_value=max_date_available
    )
    
    if len(date_range) == 2:
        start_date, end_date = sorted(date_range)
        # Asegúrate de incluir el día completo de la fecha final (hasta las 23:59:59)
        end_date_time = pd.to_datetime(end_date) + timedelta(days=1) - timedelta(seconds=1)

        df_filtered = df_results[
            (df_results['DATE_OBJ'] >= pd.to_datetime(start_date)) & 
            (df_results['DATE_OBJ'] <= end_date_time)
        ].copy()
    else:
        df_filtered = df_results.copy()


    if df_filtered.empty:
        st.warning("No hay artículos en el rango de fechas seleccionado. Intenta ampliar el rango.")
    else:
        # --- Section 1: Data Table ---
        st.subheader(f"📊 Artículos Filtrados ({len(df_filtered)} Encontrados)")
        # Solo mostrar las columnas relevantes en la tabla
        st.dataframe(df_filtered[['TITLE', 'DATE_NORMALIZED', 'URL']], use_container_width=True, hide_index=True)

        # --- Section 2: Summary Table ---
        summary_df = summarize_by_month(df_filtered)
        st.subheader("🗓️ Resumen Mensual (Período: 16-15)")
        # Mejorar la tabla de resumen con un diseño de Streamlit
        st.dataframe(
            summary_df.sort_values(by='Month', ascending=False), 
            use_container_width=True, 
            hide_index=True
        )

        # --- Section 3: Visualization (PLOTLY) ---
        st.subheader("📈 Gráfico de Publicaciones Mensuales")
        fig_plotly = create_monthly_plot_plotly(summary_df, search_term)
        
        if fig_plotly:
             # Usamos Streamlit para mostrar el gráfico de Plotly
            st.plotly_chart(fig_plotly, use_container_width=True)
        else:
            st.warning("No hay suficientes datos para generar el gráfico.")
            
        # --- Section 4: Downloads ---
        st.subheader("⬇️ Opciones de Descarga")
        
        # Eliminamos la segunda columna y el botón de PDF, dejando solo el CSV
        col1 = st.columns(1)[0]

        # CSV Download (siempre el data frame original)
        csv_buffer = io.StringIO()
        df_results.to_csv(csv_buffer, index=False)
        col1.download_button(
            label="Download Data as CSV (Completa)",
            data=csv_buffer.getvalue(),
            file_name=f'lavoz_{search_term.replace(" ", "_").lower()}_articles_full.csv',
            mime='text/csv'
        )
        
else:
    st.info("Ingresa un término de búsqueda y haz clic en '🔍 Buscar' para comenzar.")
