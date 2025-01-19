import streamlit as st
import plotly.graph_objects as go
from datetime import datetime
import pandas as pd
from main import BinanceTraderBot
import logging
from logger import trade_logger
import time

# Configuração da página
st.set_page_config(
    page_title="Binance Trading Bot",
    layout="wide",
    page_icon="📈"
)

# Título da aplicação
st.title("📈 Binance Trading Bot - EMA Strategy")

# Inicialização do bot
@st.cache_resource
def init_bot():
    return BinanceTraderBot(
        stock_code="BTC",
        operation_code="BTCUSDT",
        traded_quantity=10,
        traded_percentage=100,
        candle_period="15m"
    )

# Função para calcular EMAs
def calculate_emas(df):
    df['ema_7'] = df['close'].ewm(span=7, adjust=False).mean()
    df['ema_25'] = df['close'].ewm(span=25, adjust=False).mean()
    df['ema_99'] = df['close'].ewm(span=99, adjust=False).mean()
    return df

# Função para criar gráfico candlestick
def create_candlestick_chart(df):
    fig = go.Figure()

    # Candlesticks
    fig.add_trace(go.Candlestick(
        x=df['open_time'],
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        name="Candlesticks"
    ))

    # EMAs
    fig.add_trace(go.Scatter(
        x=df['open_time'],
        y=df['ema_7'],
        name="EMA 7",
        line=dict(color='orange', width=1)
    ))

    fig.add_trace(go.Scatter(
        x=df['open_time'],
        y=df['ema_25'],
        name="EMA 25",
        line=dict(color='blue', width=1)
    ))

    fig.add_trace(go.Scatter(
        x=df['open_time'],
        y=df['ema_99'],
        name="EMA 99",
        line=dict(color='green', width=1)
    ))

    # Layout
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=600,
        title="Candlesticks com EMAs",
        yaxis_title="Preço (USDT)",
        xaxis_title="Data/Hora",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )

    return fig

# Layout da aplicação
def main():
    # Inicializa o bot
    bot = init_bot()
    
    # Atualiza dados
    bot.updateAllData()
    
    # Calcula EMAs
    df = bot.candle_data.copy()
    df = calculate_emas(df)
    
    # Cria colunas para layout
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Exibe gráfico
        st.plotly_chart(create_candlestick_chart(df), use_container_width=True)
    
    with col2:
        # Painel de métricas
        st.subheader("📊 Métricas")
        col_metric1, col_metric2 = st.columns(2)
        
        with col_metric1:
            st.metric("Saldo Atual", f"{bot.last_stock_account_balance:.2f} {bot.stock_code}")
            st.metric("Posição Atual", "Comprado" if bot.actual_trade_position else "Vendido")
            
        with col_metric2:
            # Exibe preços atuais das EMAs
            st.metric("EMA 7", f"{df['ema_7'].iloc[-1]:.2f}")
            st.metric("EMA 25", f"{df['ema_25'].iloc[-1]:.2f}")
            st.metric("EMA 99", f"{df['ema_99'].iloc[-1]:.2f}")
        
        # Exibe últimas ordens
        st.subheader("📝 Últimas Ordens")
        if hasattr(bot, 'last_orders'):
            for order in bot.last_orders[-5:]:  # Mostra as últimas 5 ordens
                with st.expander(f"Ordem {order['orderId']}"):
                    st.write(f"**Tipo:** {order['side']}")
                    st.write(f"**Quantidade:** {order['origQty']}")
                    st.write(f"**Preço:** {order.get('price', 'MARKET')}")
                    st.write(f"**Data/Hora:** {order['timestamp']}")
        
    # Aba de logs
    st.sidebar.title("📜 Logs em Tempo Real")
    auto_refresh = st.sidebar.checkbox("Atualização automática", value=True)
    
    if auto_refresh:
        with st.sidebar:
            with st.empty():
                while True:
                    # Lê o arquivo de logs
                    try:
                        with open('historico_trades.log', 'r') as f:
                            logs = f.read()
                        st.text_area("Logs", logs, height=400)
                    except:
                        st.error("Erro ao ler arquivo de logs")
                    
                    time.sleep(5)
                    st.rerun()

if __name__ == "__main__":
    main()
