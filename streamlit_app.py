import os

# Third-party imports
import numpy as np
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh  # Componente para auto-refresh controlado

# Local application imports
from logger import trade_logger
from main import BinanceTraderBot, TradingConfig
from src.indicators import calculate_indicators, strategy_signals

# Configuração da página
st.set_page_config(
    page_title="Binance Trading Bot",
    layout="wide",
    page_icon=":chart_with_upwards_trend:"
)

# Título da aplicação
st.title("📈 Binance Trading Bot - EMA Strategy")

def init_bot(config):
    """Inicializa e retorna uma instância do bot trader"""
    if 'bot' not in st.session_state:
        try:
            st.info("Verificando conexão com API Binance...")
            from dotenv import load_dotenv
            load_dotenv()
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
            # Testa conexão obtendo dados de mercado
            test_data = bot.client_binance.get_symbol_ticker(symbol=config['operation_code'])
            if not test_data:
                raise ConnectionError("Falha ao conectar com API Binance")
            st.session_state.bot = bot
            st.success("Conexão com API Binance estabelecida com sucesso!")
        except ConnectionError as ce:
            st.error(f"Erro de conexão: {str(ce)}")
            trade_logger.log_error("Erro de conexão com API Binance", ce)
            return None
        except Exception as e:
            st.error(f"Erro ao inicializar bot: {str(e)}")
            trade_logger.log_error("Erro ao inicializar bot", e)
            return None
    return st.session_state.bot

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
        stock_code = st.text_input("Código do Ativo", value=st.session_state.bot_config['stock_code'])
        if not stock_code.isalpha() or len(stock_code) < 2 or len(stock_code) > 5:
            st.error("Código do ativo inválido. Deve conter de 2 a 5 letras.")
        else:
            st.session_state.bot_config['stock_code'] = stock_code.upper()
        operation_code = st.text_input("Par de Negociação", value=st.session_state.bot_config['operation_code'])
        if not operation_code.isalnum() or len(operation_code) < 5 or len(operation_code) > 10:
            st.error("Par de negociação inválido. Deve conter de 5 a 10 caracteres alfanuméricos.")
        else:
            st.session_state.bot_config['operation_code'] = operation_code.upper()
        traded_percentage = st.number_input("Porcentagem Negociada", 
                                            value=st.session_state.bot_config['traded_percentage'], 
                                            min_value=1, 
                                            max_value=100)
        if traded_percentage < 1 or traded_percentage > 100:
            st.error("Porcentagem deve estar entre 1% e 100%.")
        else:
            st.session_state.bot_config['traded_percentage'] = traded_percentage
        st.session_state.bot_config['candle_period'] = st.selectbox(
            "Período do Candle", 
            options=["1m", "5m", "15m", "1h", "4h", "1d"], 
            index=["1m", "5m", "15m", "1h", "4h", "1d"].index(st.session_state.bot_config['candle_period'])
        )
        st.subheader("🛑 Configurações de Risco")
        stop_loss = st.number_input("Stop Loss (%)", 
                                    value=st.session_state.bot_config['stop_loss'], 
                                    min_value=0.1, 
                                    max_value=100.0, 
                                    step=0.1)
        if stop_loss < 0.1 or stop_loss > 100:
            st.error("Stop Loss deve estar entre 0.1% e 100%.")
        else:
            st.session_state.bot_config['stop_loss'] = stop_loss
        take_profit = st.number_input("Take Profit (%)", 
                                      value=st.session_state.bot_config['take_profit'], 
                                      min_value=0.1, 
                                      max_value=100.0, 
                                      step=0.1)
        if take_profit < 0.1 or take_profit > 100:
            st.error("Take Profit deve estar entre 0.1% e 100%.")
        else:
            st.session_state.bot_config['take_profit'] = take_profit
        if stop_loss >= take_profit:
            st.error("Take Profit deve ser maior que Stop Loss.")
    return st.session_state.bot_config

def plot_ema_macd_roi(df, title='EMA(7,25) & MACD(12,26) & ROI'):
    """Plota os dados de EMA, MACD e ROI com marcações de cruzamentos de compra e venda."""
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
    buy_crossover = df[(df['signal'] == 1) & (df['signal'].shift(1) != 1)]
    sell_crossover = df[(df['signal'] == -1) & (df['signal'].shift(1) != -1)]
    if not buy_crossover.empty:
        fig.add_trace(go.Scatter(
            x=buy_crossover.index,
            y=buy_crossover['close'],
            mode='markers',
            marker=dict(symbol='triangle-up', color='green', size=10),
            name='Sinal Compra'
        ), row=1, col=1)
    if not sell_crossover.empty:
        fig.add_trace(go.Scatter(
            x=sell_crossover.index,
            y=sell_crossover['close'],
            mode='markers',
            marker=dict(symbol='triangle-down', color='red', size=10),
            name='Sinal Venda'
        ), row=1, col=1)
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
    if 'roi' in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index,
            y=df['roi'],
            line=dict(color='green', width=1),
            name='ROI'
        ), row=3, col=1)
    fig.update_layout(
        title=title,
        xaxis_rangeslider_visible=False,
        showlegend=True,
        height=800
    )
    return fig

# Controle de execução do bot
if 'bot_running' not in st.session_state:
    st.session_state.bot_running = False

def main():
    try:
        # Verifica variáveis de ambiente
        if not os.getenv('BINANCE_API_KEY') or not os.getenv('BINANCE_SECRET_KEY'):
            st.error("⚠️ Chaves da API Binance não encontradas!")
            st.info("Copie o arquivo .env.example para .env e configure suas chaves.")
            return

        # Obtém configurações e inicializa o bot
        with st.spinner("Inicializando..."):
            config = get_bot_config()
            bot = init_bot(config)
            if bot is None:
                st.error("❌ Falha ao inicializar o bot.")
                return

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

        # Atualiza dados e status do bot
        with st.spinner("Atualizando dados do mercado..."):
            try:
                bot.updateAllData()
                if st.session_state.bot_running and not bot._running:
                    bot.start()
                    st.success("Bot iniciado com sucesso!")
                elif not st.session_state.bot_running and bot._running:
                    bot.stop()
                    st.info("Bot parado com sucesso!")
                if st.session_state.bot_running:
                    bot.execute()
            except Exception as e:
                st.error(f"❌ Erro durante execução: {str(e)}")
                trade_logger.log_error("Erro durante execução do bot", e)
                st.session_state.bot_running = False
                return

        try:
            # Calcula indicadores
            if bot.candle_data is not None:
                df = bot.candle_data.copy()
                df = calculate_indicators(df)
                df['signal'] = strategy_signals(df)
            else:
                st.error("Não foi possível obter dados do mercado. Verifique sua conexão.")
                return

            # Layout principal
            col1, col2 = st.columns([3, 1])
            with col1:
                fig = plot_ema_macd_roi(df)
                st.plotly_chart(fig, use_container_width=True)
            with col2:
                st.subheader("📊 Status do Bot")
                col_status, col_position, col_balance = st.columns(3)
                with col_status:
                    st.metric(
                        "Estado do Bot",
                        "🟢 ATIVO" if bot._running else "🔴 PARADO",
                        help="Estado atual do bot"
                    )
                with col_position:
                    position_value = "COMPRADO" if bot.actual_trade_position else "VENDIDO"
                    st.metric(
                        "Posição Atual",
                        position_value,
                        delta="COMPRADO" if bot.actual_trade_position else "VENDIDO",
                        delta_color="normal" if bot.actual_trade_position else "inverse",
                        help="Posição atual do bot no mercado"
                    )
                with col_balance:
                    balance_delta = bot.last_stock_account_balance - bot.initial_balance
                    st.metric(
                        "Saldo",
                        f"{bot.last_stock_account_balance:.8f} {bot.stock_code}",
                        delta=f"{balance_delta:+.8f}",
                        delta_color="normal" if balance_delta >= 0 else "inverse",
                        help="Saldo atual e variação desde o início"
                    )
                st.subheader("📈 Indicadores Técnicos")
                col_price, col_ema, col_macd = st.columns(3)
                with col_price:
                    current_price = df['close'].iloc[-1]
                    price_change = df['close'].pct_change().iloc[-1] * 100
                    st.metric(
                        "Preço Atual",
                        f"{current_price:.2f} {bot.config.quote_asset}",
                        delta=f"{price_change:+.2f}%",
                        delta_color="normal" if price_change >= 0 else "inverse",
                        help="Preço atual e variação percentual"
                    )
                    st.metric(
                        "Volume 24h",
                        f"{df['volume'].iloc[-1]:.2f}",
                        help="Volume de negociação nas últimas 24 horas"
                    )
                    roi_value = df['roi'].iloc[-1] * 100
                    st.metric(
                        "ROI",
                        f"{roi_value:.2f}%",
                        delta=f"{roi_value:+.2f}%",
                        delta_color="normal" if roi_value >= 0 else "inverse",
                        help="Retorno sobre o investimento acumulado"
                    )
                with col_ema:
                    st.metric("EMA 7", f"{df['ema_7'].iloc[-1]:.2f}")
                    st.metric("EMA 25", f"{df['ema_25'].iloc[-1]:.2f}")
                    st.metric("EMA 50", f"{df['ema_50'].iloc[-1]:.2f}")
                    st.metric("EMA 100", f"{df['ema_100'].iloc[-1]:.2f}")
                with col_macd:
                    st.metric("MACD", f"{df['macd_line'].iloc[-1]:.2f}")
                    st.metric("Sinal MACD", f"{df['signal_line'].iloc[-1]:.2f}")
                    st.metric("RSI", f"{df['rsi'].iloc[-1]:.2f}")
                    max_drawdown = ((df['close'].max() - df['close'].min()) / df['close'].max()) * 100
                    st.metric(
                        "Drawdown Máx.",
                        f"{max_drawdown:.2f}%",
                        help="Maior queda percentual do preço"
                    )
                if hasattr(bot, 'last_trade') and bot.last_trade:
                    st.subheader("🔄 Último Trade")
                    trade_cols = st.columns(4)
                    with trade_cols[0]:
                        st.metric("Tipo", bot.last_trade['side'])
                    with trade_cols[1]:
                        st.metric("Quantidade", f"{bot.last_trade['quantity']:.8f}")
                    with trade_cols[2]:
                        st.metric("Preço", f"{bot.last_trade['price']:.2f}")
                    with trade_cols[3]:
                        st.metric("Horário", bot.last_trade['timestamp'])
            st.sidebar.title("📜 Monitor em Tempo Real")
            log_tabs = st.sidebar.tabs(["📊 Status", "📈 Sinais", "🔄 Trades"])
            def load_logs():
                try:
                    with open('src/logs/trading_bot.log', 'r', encoding='utf-8') as f:
                        logs = f.readlines()
                        return logs[-50:]
                except Exception as e:
                    st.error(f"Erro ao ler arquivo de logs: {str(e)}")
                    return []
            def parse_log_entry(log):
                if "STATUS DO BOT" in log:
                    return "status", log
                elif "INDICADORES TÉCNICOS" in log:
                    return "sinais", log
                elif "ORDEM EXECUTADA" in log:
                    return "trades", log
                return "outros", log
            if st.session_state.bot_running:
                logs = load_logs()
                status_logs = []
                signal_logs = []
                trade_logs = []
                for log in logs:
                    log_type, content = parse_log_entry(log)
                    if log_type == "status":
                        status_logs.append(content)
                    elif log_type == "sinais":
                        signal_logs.append(content)
                    elif log_type == "trades":
                        trade_logs.append(content)
                with log_tabs[0]:
                    if status_logs:
                        st.code("".join(reversed(status_logs[-10:])), language="plain")
                    else:
                        st.info("Nenhum log de status disponível")
                with log_tabs[1]:
                    if signal_logs:
                        st.code("".join(reversed(signal_logs[-10:])), language="plain")
                    else:
                        st.info("Nenhum log de sinais disponível")
                with log_tabs[2]:
                    if trade_logs:
                        st.code("".join(reversed(trade_logs[-10:])), language="plain")
                    else:
                        st.info("Nenhuma ordem executada ainda")
        except Exception as e:
            st.error(f"❌ Erro ao atualizar interface: {str(e)}")
            trade_logger.log_error("Erro ao atualizar interface", e)
            st.session_state.bot_running = False
    except Exception as e:
        st.error(f"❌ Erro geral: {str(e)}")
        trade_logger.log_error("Erro geral na interface", e)
        st.session_state.bot_running = False

if __name__ == "__main__":
    # Utiliza o st_autorefresh para atualizar a interface automaticamente a cada 10 segundos (10000 ms).
    refresh_count = st_autorefresh(interval=10000, limit=100, key="auto_refresh")
    # Exibe o tempo de execução na sidebar (cada refresh equivale a 10 segundos)
    st.sidebar.metric("⏱️ Tempo de Execução", f"{refresh_count * 10} segundos")
    main()
