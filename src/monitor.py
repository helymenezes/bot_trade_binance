import pandas as pd
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, Any, Optional

@dataclass
class BotStatus:
    """Classe para armazenar o status atual do bot"""
    timestamp: str
    is_running: bool
    position: str
    balance: float
    current_price: float
    asset: str
    quote_asset: str
    last_signal: str
    indicators: Dict[str, float]
    last_trade: Optional[Dict[str, Any]] = None

class BotMonitor:
    """Classe para monitorar e registrar o status do bot"""
    
    def __init__(self, logger):
        self.logger = logger
        self.last_status = None
    
    def update_status(self, bot, df_indicators) -> BotStatus:
        """Atualiza e registra o status atual do bot"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Coleta indicadores técnicos
        indicators = {
            'ema_7': df_indicators['ema_7'].iloc[-1],
            'ema_25': df_indicators['ema_25'].iloc[-1],
            'ema_50': df_indicators['ema_50'].iloc[-1],
            'ema_100': df_indicators['ema_100'].iloc[-1],
            'macd': df_indicators['macd_line'].iloc[-1],
            'signal': df_indicators['signal_line'].iloc[-1],
            'rsi': df_indicators['rsi'].iloc[-1],
            'roi': df_indicators['roi'].iloc[-1] if 'roi' in df_indicators.columns else 0.0
        }
        
        # Determina o último sinal
        signal = 'COMPRA' if df_indicators['signal'].iloc[-1] == 1 else 'VENDA'
        
        # Cria objeto de status
        status = BotStatus(
            timestamp=current_time,
            is_running=bot._running,
            position='COMPRADO' if bot.actual_trade_position else 'VENDIDO',
            balance=bot.last_stock_account_balance,
            current_price=df_indicators['close'].iloc[-1],
            asset=bot.stock_code,
            quote_asset=bot.config.quote_asset,
            last_signal=signal,
            indicators=indicators,
            last_trade=getattr(bot, 'last_trade', None)
        )
        
        self.last_status = status
        self._log_status(status)
        return status
    
    def _log_status(self, status: BotStatus):
        """Registra o status atual nos logs"""
        
        # Log de status do bot
        status_msg = (
            f"\n{'='*50}"
            f"\nSTATUS DO BOT em {status.timestamp}"
            f"\n{'='*50}"
            f"\nEstado: {'EXECUTANDO' if status.is_running else 'PARADO'}"
            f"\nPosição: {status.position}"
            f"\nBalanço: {status.balance:.8f} {status.asset}"
            f"\nPreço Atual: {status.current_price:.2f} {status.quote_asset}"
        )
        
        # Log de indicadores técnicos
        indicators_msg = (
            f"\n\nINDICADORES TÉCNICOS:"
            f"\n{'-'*20}"
            f"\nEMA 7: {status.indicators['ema_7']:.2f}"
            f"\nEMA 25: {status.indicators['ema_25']:.2f}"
            f"\nEMA 50: {status.indicators['ema_50']:.2f}"
            f"\nEMA 100: {status.indicators['ema_100']:.2f}"
            f"\nMACD: {status.indicators['macd']:.2f}"
            f"\nSinal MACD: {status.indicators['signal']:.2f}"
            f"\nRSI: {status.indicators['rsi']:.2f}"
            f"\nROI: {status.indicators['roi']*100:.2f}%"
        )
        
        # Log de sinais e trades
        signals_msg = (
            f"\n\nSINAIS E TRADES:"
            f"\n{'-'*20}"
            f"\nÚltimo Sinal: {status.last_signal}"
        )
        
        if status.last_trade:
            signals_msg += (
                f"\nÚltimo Trade:"
                f"\n- Tipo: {status.last_trade.get('side', 'N/A')}"
                f"\n- Quantidade: {status.last_trade.get('quantity', 'N/A')}"
                f"\n- Preço: {status.last_trade.get('price', 'N/A')}"
                f"\n- Horário: {status.last_trade.get('timestamp', 'N/A')}"
            )
        
        # Registra todas as mensagens
        full_msg = status_msg + indicators_msg + signals_msg
        self.logger.log_info(full_msg)