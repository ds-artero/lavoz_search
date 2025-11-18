import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta

# --- Configuración de la Página ---
st.set_page_config(
    page_title="Análisis de Ventas con Plotly",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Generación de Datos de Muestra (TimeSeries) ---
@st.cache_data
def load_data():
    """Genera datos de ventas simulados para el último año."""
    start_date = datetime.now() - timedelta(days=365)
    dates = pd.date_range(start=start_date, end=datetime.now(), freq='D')
    
    # Simulación de valores de ventas
    data = pd.DataFrame({
        'Fecha': dates,
        'Ventas': (
            100 + 
            5 * dates.dayofyear + # Tendencia general
            50 * (dates.dayofweek == 6).astype(int) + # Pico en domingos
            20 * pd.np.random.randn(len(dates)) # Ruido
        ).clip(lower=0) # Asegura que no haya ventas negativas
    })
    
    # Calcula el promedio móvil simple (SMA) de 7 días
    data['Promedio_7D'] = data['Ventas'].rolling(window=7, min_periods=1).mean()
    
    return data

df = load_data()

# --- Título y Encabezado de la Aplicación ---
st.title("📈 Dashboard de Análisis de Ventas Diarias")
st.markdown("Utiliza el filtro lateral para ajustar el rango de fechas y visualizar el promedio móvil.")

# --- Barra Lateral (Filtros) ---
st.sidebar.header("Filtros de Visualización")

# Obtener fechas mínimas y máximas de los datos
min_date = df['Fecha'].min().date()
max_date = df['Fecha'].max().date()

# Filtro de rango de fechas
date_range = st.sidebar.date_input(
    "Selecciona un Rango de Fechas",
    [min_date, max_date],
    min_value=min_date,
    max_value=max_date
)

# Asegurarse de que el rango de fechas tenga sentido (manejo de un solo valor o rango invertido)
if len(date_range) == 2:
    start_date, end_date = sorted(date_range)
    # Convertir a objetos datetime para la comparación
    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date)
    
    # Filtrar el DataFrame
    df_filtered = df[(df['Fecha'] >= start_date) & (df['Fecha'] <= end_date)]
else:
    # Si solo se selecciona una fecha (o la selección está incompleta), usar el DataFrame completo
    df_filtered = df


# --- Visualización Principal con Plotly ---
st.header("Ventas Diarias vs. Promedio Móvil (7 días)")

if df_filtered.empty:
    st.warning("No hay datos para el rango de fechas seleccionado. Por favor, ajusta los filtros.")
else:
    # Crear el gráfico de líneas con Plotly Express
    fig = px.line(
        df_filtered,
        x='Fecha',
        y='Ventas',
        title='Evolución de Ventas Diarias',
        labels={
            "Ventas": "Ventas (€)",
            "Fecha": "Fecha"
        }
    )

    # Añadir la línea del promedio móvil de 7 días (la 'línea promedio')
    fig.add_scatter(
        x=df_filtered['Fecha'], 
        y=df_filtered['Promedio_7D'], 
        mode='lines', 
        name='Promedio Móvil (7D)',
        line=dict(color='red', width=3)
    )
    
    # Ajustes de diseño para mejor visualización
    fig.update_layout(
        xaxis_title="Fecha",
        yaxis_title="Ventas (€)",
        hovermode="x unified",
        template="plotly_white",
        height=500
    )
    
    # Mostrar el gráfico en Streamlit
    st.plotly_chart(fig, use_container_width=True)


# --- Visualización de Datos Crudos (Opcional) ---
st.header("Datos Filtrados")
st.dataframe(df_filtered.tail(10), use_container_width=True, hide_index=True)

# Información adicional del promedio
st.markdown(f"""
---
**Nota sobre el Promedio Móvil (Línea Promedio):**
El promedio móvil (Promedio_7D) se ha calculado con una ventana de **7 días**. 
Este indicador ayuda a suavizar las fluctuaciones diarias y a identificar la tendencia subyacente.
""")
