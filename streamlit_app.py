# Standard library imports
import logging
import os
import time
from datetime import datetime

# Third-party imports
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# Local application imports
from logger import trade_logger
from main import BinanceTraderBot, TradingConfig
from src.indicators import calculate_indicators, strategy_signals

# Configuração da página
st.set_page_config(
    page_title="Binance Trading Bot",
    layout="wide",
    page_icon=":chart_with_upwards_trend:"  # Ícone compatível com UTF-8
)

# Título da aplicação
st.title("📈 Binance Trading Bot - EMA Strategy")

def init_bot(config):
    """Inicializa e retorna uma instância do bot trader com mecanismo de retry"""
    @st.cache_resource
    def _init_bot(config):
        max_retries = 3
        retry_delay = 5  # segundos
        
        for attempt in range(max_retries):
            try:
                # Verifica conexão com API Binance
                st.info(f"Tentativa {attempt + 1} de {max_retries} de conexão com API Binance...")
                
                # Cria configuração a partir dos parâmetros
                trading_config = TradingConfig(
                    api_key=os.getenv('BINANCE_API_KEY'),
                    secret_key=os.getenv('BINANCE_SECRET_KEY'),
                    trading_pair=config['operation_code'],
                    base_asset=config['stock_code'],
                    quote_asset=config['quote_asset'],
                    trading_percentage=config['traded_percentage'],
                    stop_loss=config['stop_loss'],
                    take_profit=config['take_profit'],
                    candle_interval=config['candle_period']
                )
                
                bot = BinanceTraderBot(trading_config)
                
                # Testa conexão obtendo dados de mercado com retry
                for ping_attempt in range(3):
                    try:
                        # Tenta ping primeiro
                        bot.client_binance.ping()
                        # Se ping ok, tenta dados do mercado
                        test_data = bot.client_binance.get_symbol_ticker(symbol=config['operation_code'])
                        if test_data:
                            st.success("Conexão com API Binance estabelecida com sucesso!")
                            return bot
                    except Exception as ping_error:
                        if ping_attempt < 2:  # Se não é a última tentativa
                            st.warning(f"Tentativa {ping_attempt + 1} de ping falhou, tentando novamente...")
                            time.sleep(2)
                        else:
                            raise ping_error
                
                raise ConnectionError("Falha ao conectar com API Binance após várias tentativas")
                
            except ConnectionError as ce:
                if attempt < max_retries - 1:  # Se ainda não é a última tentativa
                    st.warning(f"Tentativa {attempt + 1} falhou. Tentando novamente em {retry_delay} segundos...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Aumenta o tempo de espera entre tentativas
                else:
                    st.error(f"Erro de conexão após {max_retries} tentativas: {str(ce)}")
                    trade_logger.log_error("Erro de conexão com API Binance", ce)
                    return None
            except Exception as e:
                st.error(f"Erro ao inicializar bot: {str(e)}")
                trade_logger.log_error("Erro ao inicializar bot", e)
                return None
            
    bot = _init_bot(config)
    if bot is None:
        st.stop()
    return bot

# Configurações do bot
def get_bot_config():
    if 'bot_config' not in st.session_state:
        st.session_state.bot_config = {
            'stock_code': "BTC",
            'operation_code': "BTCUSDC",
            'quote_asset': "USDC",
            'traded_percentage': 100,
            'candle_period': "1h",
            'stop_loss': 1.0,
            'take_profit': 1.0
        }
    
    with st.sidebar:
        st.subheader("⚙️ Configurações do Bot")
        
        # Validação do código do ativo
        stock_code = st.text_input("Código do Ativo", value=st.session_state.bot_config['stock_code'])
        if not stock_code.isalpha() or len(stock_code) < 2 or len(stock_code) > 5:
            st.error("Código do ativo inválido. Deve conter de 2 a 5 letras.")
        else:
            st.session_state.bot_config['stock_code'] = stock_code.upper()
        
        # Validação do par de negociação
        operation_code = st.text_input("Par de Negociação", value=st.session_state.bot_config['operation_code'])
        if not operation_code.isalnum() or len(operation_code) < 5 or len(operation_code) > 10:
            st.error("Par de negociação inválido. Deve conter de 5 a 10 caracteres alfanuméricos.")
        else:
            st.session_state.bot_config['operation_code'] = operation_code.upper()
        
        # Validação da porcentagem negociada
        traded_percentage = st.number_input("Porcentagem Negociada", 
                                          value=st.session_state.bot_config['traded_percentage'], 
                                          min_value=1, 
                                          max_value=100)
        if traded_percentage < 1 or traded_percentage > 100:
            st.error("Porcentagem deve estar entre 1% e 100%.")
        else:
            st.session_state.bot_config['traded_percentage'] = traded_percentage
        
        # Seleção do período do candle
        st.session_state.bot_config['candle_period'] = st.selectbox(
            "Período do Candle", 
            options=["1m", "5m", "15m", "1h", "4h", "1d"], 
            index=["1m", "5m", "15m", "1h", "4h", "1d"].index(st.session_state.bot_config['candle_period'])
        )
        
        st.subheader("🛑 Configurações de Risco")
        
        # Validação do stop loss
        stop_loss = st.number_input(
            "Stop Loss (%)", 
            value=st.session_state.bot_config['stop_loss'], 
            min_value=0.1, 
            max_value=100.0, 
            step=0.1
        )
        if stop_loss < 0.1 or stop_loss > 100:
            st.error("Stop Loss deve estar entre 0.1% e 100%.")
        else:
            st.session_state.bot_config['stop_loss'] = stop_loss
        
        # Validação do take profit
        take_profit = st.number_input("Take Profit (%)", 
                                    value=st.session_state.bot_config['take_profit'], 
                                    min_value=0.1, 
                                    max_value=100.0, 
                                    step=0.1)
        if take_profit < 0.1 or take_profit > 100:
            st.error("Take Profit deve estar entre 0.1% e 100%.")
        else:
            st.session_state.bot_config['take_profit'] = take_profit
            
        # Verificação de consistência entre stop loss e take profit
        if stop_loss >= take_profit:
            st.error("Take Profit deve ser maior que Stop Loss.")
    
    return st.session_state.bot_config

from src.indicators import calculate_indicators, strategy_signals

def plot_ema_macd_roi(df, title='EMA(7,25) & MACD(12,26) & ROI'):
    """
    Plota os dados de EMA, MACD e ROI com marcações de cruzamentos de compra e venda.
    """
    # Criação dos subplots
    fig = make_subplots(
        rows=3, 
        cols=1, 
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.6, 0.2, 0.2],
        specs=[
            [{"secondary_y": True}],
            [{"secondary_y": False}],
            [{"secondary_y": False}]
        ]
    )

    # Adicionar candles e EMAs
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        name='Candles'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df.index,
        y=df['ema_7'],
        line=dict(color='blue', width=1),
        name='EMA 7'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df.index,
        y=df['ema_25'],
        line=dict(color='red', width=1),
        name='EMA 25'
    ), row=1, col=1)

    # Identificar os cruzamentos corretos
    buy_crossover = df[(df['signal'] == 1) & (df['signal'].shift(1) != 1)]
    sell_crossover = df[(df['signal'] == -1) & (df['signal'].shift(1) != -1)]

    # Adicionar sinais de compra e venda ao gráfico
    if not buy_crossover.empty:
        fig.add_trace(go.Scatter(
            x=buy_crossover.index,
            y=buy_crossover['close'],
            mode='markers',
            marker=dict(symbol='triangle-up', color='green', size=10),
            name='Cruzamento Compra'
        ), row=1, col=1)

    if not sell_crossover.empty:
        fig.add_trace(go.Scatter(
            x=sell_crossover.index,
            y=sell_crossover['close'],
            mode='markers',
            marker=dict(symbol='triangle-down', color='red', size=10),
            name='Cruzamento Venda'
        ), row=1, col=1)

    # MACD
    fig.add_trace(go.Scatter(
        x=df.index,
        y=df['macd_line'],
        line=dict(color='blue', width=1),
        name='MACD'
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=df.index,
        y=df['signal_line'],
        line=dict(color='orange', width=1),
        name='Sinal'
    ), row=2, col=1)

    fig.add_trace(go.Bar(
        x=df.index,
        y=df['macd_histogram'],
        marker_color=np.where(df['macd_histogram'] >= 0, 'green', 'red'),
        name='Histograma'
    ), row=2, col=1)

    # ROI (se existir)
    if 'roi' in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index,
            y=df['roi'],
            line=dict(color='green', width=1),
            name='ROI'
        ), row=3, col=1)

    # Layout do gráfico
    fig.update_layout(
        title=title,
        xaxis_rangeslider_visible=False,
        showlegend=True,
        height=800
    )

    # Exibir gráfico no Streamlit
    st.plotly_chart(fig, use_container_width=True)

# Controle de execução do bot
if 'bot_running' not in st.session_state:
    st.session_state.bot_running = False

# Layout da aplicação
def main():
    # Obtém configurações e inicializa o bot
    config = get_bot_config()
    bot = init_bot(config)
    
    # Controles de execução
    st.sidebar.subheader("🚦 Controle do Bot")
    
    if not st.session_state.bot_running:
        if st.sidebar.button("▶️ Iniciar Trader", type="primary"):
            st.session_state.bot_running = True
            st.rerun()
    else:
        if st.sidebar.button("⏹️ Parar Trader", type="secondary"):
            st.session_state.bot_running = False
            st.rerun()
    
    # Atualiza dados
    bot.updateAllData()
    
    # Executa o bot se estiver rodando
    if st.session_state.bot_running:
        bot.execute()
    
    # Calcula indicadores
    df = bot.candle_data.copy()
    df = calculate_indicators(df)
    
    # Calcula sinais de estratégia
    df['signal'] = strategy_signals(df)
    
    # Cria colunas para layout
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Exibe gráfico
        plot_ema_macd_roi(df)
    
    with col2:
        # Painel de métricas
        st.subheader("📊 Métricas")
        col_metric1, col_metric2, col_metric3 = st.columns(3)
        
        with col_metric1:
            st.metric("Saldo Atual", f"{bot.last_stock_account_balance:.2f} {bot.stock_code}")
            st.metric("Posição Atual", "Comprado" if bot.actual_trade_position else "Vendido")
            st.metric("Preço Atual", f"{df['close'].iloc[-1]:.2f}")
            st.metric("Volume 24h", f"{df['volume'].iloc[-1]:.2f}")
            
        with col_metric2:
            st.metric("EMA 7", f"{df['ema_7'].iloc[-1]:.2f}")
            st.metric("EMA 25", f"{df['ema_25'].iloc[-1]:.2f}")
            st.metric("EMA 50", f"{df['ema_50'].iloc[-1]:.2f}")
            st.metric("EMA 100", f"{df['ema_100'].iloc[-1]:.2f}")
            
        with col_metric3:
            st.metric("RSI", f"{df['rsi'].iloc[-1]:.2f}")
            st.metric("MACD", f"{df['macd_line'].iloc[-1]:.2f}")
            st.metric("Sinal MACD", f"{df['signal_line'].iloc[-1]:.2f}")
            
            # Exibe ROI com cor verde/vermelho
            roi_value = df['roi'].iloc[-1] * 100
            roi_color = "green" if roi_value >= 0 else "red"
            st.metric("ROI", f"{roi_value:.2f}%", delta_color="off", 
                     help="Retorno sobre o investimento acumulado",
                     label_visibility="visible")
            
            # Exibe lucro/prejuízo atual
            profit = bot.last_stock_account_balance - bot.initial_balance
            profit_color = "green" if profit >= 0 else "red"
            st.metric("Lucro/Prejuízo", 
                     f"{profit:.2f} {bot.stock_code}", 
                     delta_color="off",
                     help="Diferença entre saldo atual e saldo inicial",
                     label_visibility="visible")
            
            # Exibe drawdown máximo
            max_drawdown = df['close'].max() - df['close'].min()
            st.metric("Drawdown Máx.", f"{max_drawdown:.2f}")
            
        # Exibe últimas ordens
        st.subheader("📉 Últimas Ordens")
        if hasattr(bot, 'last_orders'):
            for order in bot.last_orders[-5:]:  # Mostra as últimas 5 ordens
                with st.expander(f"Ordem {order['orderId']}"):
                    st.write(f"**Tipo:** {order['side']}")
                    st.write(f"**Quantidade:** {order['origQty']}")
                    st.write(f"**Preço:** {order.get('price', 'MARKET')}")
                    st.write(f"**Data/Hora:** {order['timestamp']}")
        
    # Aba de logs
    st.sidebar.title("📜 Logs em Tempo Real")
    
    # Container para logs com auto-scroll
    log_container = st.sidebar.empty()
    
    def load_logs():
        try:
            with open('src/logs/trading_bot.log', 'r', encoding='utf-8') as f:
                logs = f.readlines()
                return logs[-30:]  # Últimas 30 entradas
        except Exception as e:
            st.error(f"Erro ao ler arquivo de logs: {str(e)}")
            return []
    
    # Atualiza o gráfico a cada 5 segundos
    @st.cache_data(ttl=5)
    def update_chart_data(bot):
        bot.updateAllData()
        df = bot.candle_data.copy()
        df = calculate_indicators(df)
        df['signal'] = strategy_signals(df)
        return df
    
    # Atualiza logs em tempo real
    if st.session_state.bot_running:
        logs = load_logs()
        formatted_logs = "".join(reversed(logs))  # Inverte para mostrar mais recentes primeiro
        log_container.code(formatted_logs, language="plain")
        
        # Rerun a cada 2 segundos se o bot estiver rodando
        time.sleep(2)
        st.rerun()

if __name__ == "__main__":
    main()
