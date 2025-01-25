import pandas as pd
import numpy as np

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula indicadores técnicos para análise de mercado.
    
    Args:
        df: DataFrame com dados de preços (deve conter coluna 'close')
        
    Returns:
        DataFrame com colunas adicionais de indicadores
        
    Calcula:
    - EMA 7 e 25 períodos
    - MACD (12, 26, 9)
    - RSI (14 períodos)
    - ROI (Return on Investment)
    """
    df['ema_7'] = df['close'].ewm(span=7, adjust=False).mean()
    df['ema_25'] = df['close'].ewm(span=25, adjust=False).mean()
    df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema_100'] = df['close'].ewm(span=100, adjust=False).mean()
    ema_12 = df['close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd_line'] = ema_12 - ema_26 
    df['signal_line'] = df['macd_line'].ewm(span=9, adjust=False).mean()
    df['macd_histogram'] = df['macd_line'] - df['signal_line']

    # Adicionando RSI
    close_diff = df['close'].diff()
    up = close_diff.clip(lower=0)
    down = -close_diff.clip(upper=0)

    ema_up = up.ewm(alpha=1/14, adjust=False).mean()
    ema_down = down.ewm(alpha=1/14, adjust=False).mean()

    rs = ema_up / ema_down
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # Calcula ROI acumulado
    df['roi'] = (df['close'].pct_change() + 1).cumprod() - 1
    
    return df

def strategy_signals(df):
    """
    Gera sinais de compra (1) e venda (-1) baseados em cruzamentos de EMA e MACD.
    Detecta apenas o primeiro cruzamento e perpetua o sinal até o próximo cruzamento oposto.
    """
    # Valida colunas necessárias
    required_cols = ['ema_7', 'ema_25', 'macd_line', 'signal_line']
    if not all(col in df.columns for col in required_cols):
        raise ValueError(f"DataFrame deve conter as colunas: {required_cols}")
        
    # Condições de compra e venda
    buy_condition = (df['ema_7'] < df['ema_25']) & (df['macd_line'] > df['signal_line'])
    sell_condition = (df['ema_7'] > df['ema_25']) & (df['macd_line'] < df['signal_line'])
    
    # Detecta os cruzamentos únicos
    buy_crossover = buy_condition & ~(buy_condition.shift(1, fill_value=False))
    sell_crossover = sell_condition & ~(sell_condition.shift(1, fill_value=False))
    
    # Inicializa a coluna de sinais
    df['signal'] = 0
    
    # Aplica os cruzamentos como sinais
    df.loc[buy_crossover, 'signal'] = 1
    df.loc[sell_crossover, 'signal'] = -1
    
    # Perpetua o sinal até o próximo cruzamento oposto
    df['signal'] = df['signal'].replace(0, np.nan).ffill().fillna(0)
    
    return df['signal']
