import os
import time
from datetime import datetime
import logging
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from binance.client import Client
from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_TYPE_MARKET
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv
from logger import trade_logger
from dataclasses import dataclass
from src.indicators import calculate_indicators, strategy_signals

# Carrega variáveis de ambiente
load_dotenv()

@dataclass
class TradingConfig:
    """Configurações de trading carregadas do arquivo .env"""
    api_key: str
    secret_key: str
    trading_pair: str
    base_asset: str
    quote_asset: str
    trading_percentage: float
    stop_loss: float
    take_profit: float
    candle_interval: str

    @classmethod
    def from_env(cls):
        """Cria configurações a partir de variáveis de ambiente"""
        return cls(
            api_key=os.getenv('BINANCE_API_KEY'),
            secret_key=os.getenv('BINANCE_SECRET_KEY'),
            trading_pair=os.getenv('TRADING_PAIR', 'BTCUSDC'),
            base_asset=os.getenv('BASE_ASSET', 'BTC'),
            quote_asset=os.getenv('QUOTE_ASSET', 'USDC'),
            trading_percentage=float(os.getenv('TRADING_PERCENTAGE', 95)),
            stop_loss=float(os.getenv('STOP_LOSS', 1.0)),
            take_profit=float(os.getenv('TAKE_PROFIT', 1.0)),
            candle_interval=os.getenv('CANDLE_INTERVAL', '1h')
        )


# Configurar API

class BinanceTraderBot:
    """Classe principal do bot de trading para a Binance.
    
    Attributes:
        stock_code (str): Código do ativo a ser negociado (ex: 'BTC')
        operation_code (str): Par de negociação (ex: 'BTCUSDC')
        traded_quantity (float): Quantidade a ser negociada
        traded_percentage (float): Porcentagem do saldo a ser usada
        candle_period (str): Período das velas (ex: '1h')
        actual_trade_position (bool): Indica se está em posição comprada
        _running (bool): Estado de execução do bot
        initial_balance (float): Saldo inicial para cálculo de ROI
        stop_loss (float): Stop loss em porcentagem
        take_profit (float): Take profit em porcentagem
        account_data (dict): Dados da conta Binance
        last_stock_account_balance (float): Último saldo do ativo
        candle_data (pd.DataFrame): Dados históricos do ativo
        api_key (str): Chave API da Binance
        secret_key (str): Chave secreta da Binance
        client_binance (Client): Instância do cliente Binance
    """
    
    def __init__(self, config: TradingConfig):
        self.config = config
        self.stock_code = config.base_asset
        self.operation_code = config.trading_pair
        self.traded_percentage = config.trading_percentage
        self.candle_period = config.candle_interval
        self.stop_loss = config.stop_loss
        self.take_profit = config.take_profit
        
        self.actual_trade_position = False
        self._running = False  # Estado de execução do bot
        self.initial_balance = 0.0  # Saldo inicial para cálculo de ROI
        
        # Inicialização dos atributos de dados
        self.account_data = None
        self.last_stock_account_balance = 0.0
        self.candle_data = None
        
        if not self.config.api_key or not self.config.secret_key:
            raise ValueError("API Key ou Secret Key não encontradas nas variáveis de ambiente")
            
        try:
            # Inicializa o cliente Binance
            self.client_binance = Client(
                self.config.api_key,
                self.config.secret_key,
                tld='com'
            )
            
            # Testa a conexão com retry
            max_retries = 3
            retry_delay = 5
            for attempt in range(max_retries):
                try:
                    self.client_binance.ping()
                    break
                except Exception as e:
                    if attempt == max_retries - 1:  # Última tentativa
                        trade_logger.log_error(f"Falha na conexão após {max_retries} tentativas", e)
                        raise
                    trade_logger.log_info(f"Tentativa {attempt + 1} falhou, tentando novamente em {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
            self.updateAllData()
            trade_logger.log_info("Robô Trader iniciado com sucesso")
            print("Robô Trader iniciado...")
        except BinanceAPIException as e:
            trade_logger.log_error("Erro ao inicializar o cliente Binance", e)
            raise

    def updateAllData(self):
        """Atualiza todos os dados da conta com mecanismo de retry"""
        max_retries = 3
        retry_delay = 5  # segundos
        
        for attempt in range(max_retries):
            try:
                # Tenta ping na API primeiro para verificar conexão
                self.client_binance.ping()
                
                self.account_data = self.getUpdatedAccountData()
                self.last_stock_account_balance = self.getLastStockAccountBalance()
                self.actual_trade_position = self.getActualTradePosition()
                self.candle_data = self.getStockData_ClosePrice_OpenTime()
                
                # Inicializa saldo inicial na primeira execução
                if self.initial_balance == 0.0 and self.last_stock_account_balance > 0:
                    self.initial_balance = self.last_stock_account_balance
                    trade_logger.log_info(f"Saldo inicial definido: {self.initial_balance}")
                
                # Verifica stop loss e take profit se estiver em posição
                if self.actual_trade_position and len(self.candle_data) > 0:
                    current_price = self.candle_data['close'].iloc[-1]
                    entry_price = self.candle_data['close'].iloc[-2]  # Preço de entrada
                    
                    # Calcula variação percentual
                    price_change = ((current_price - entry_price) / entry_price) * 100
                    
                    # Verifica stop loss
                    if price_change <= -self.stop_loss:
                        trade_logger.log_info(f"Stop loss atingido: {price_change:.2f}%")
                        self.sellStock()
                    
                    # Verifica take profit
                    if price_change >= self.take_profit:
                        trade_logger.log_info(f"Take profit atingido: {price_change:.2f}%")
                        self.sellStock()
                
                # Se chegou aqui, a atualização foi bem sucedida
                return
                
            except BinanceAPIException as e:
                if attempt < max_retries - 1:  # Se ainda não é a última tentativa
                    trade_logger.log_info(f"Tentativa {attempt + 1} falhou. Tentando novamente em {retry_delay} segundos...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Aumenta o tempo de espera entre tentativas
                else:
                    trade_logger.log_error("Erro ao atualizar dados após várias tentativas", e)
                    raise
            except Exception as e:
                trade_logger.log_error("Erro ao atualizar dados", e)
                raise

    def getUpdatedAccountData(self):
        """Busca informações atualizadas da conta Binance"""
        return self.client_binance.get_account()


    def getLastStockAccountBalance(self):
        """Busca o último balanço da conta na stock escolhida"""
        if self.account_data and "balances" in self.account_data:
            for stock in self.account_data["balances"]:
                if stock["asset"] == self.stock_code:
                    return float(stock["free"])
        return 0.0

    def getActualTradePosition(self):
        """Verifica se a posição atual é comprada ou vendida"""
        return self.last_stock_account_balance > 0.001

    def getStockData_ClosePrice_OpenTime(self):
        """Busca os dados do ativo no período"""
        try:
            candles = self.client_binance.get_klines(
                symbol=self.operation_code,
                interval=self.candle_period,
                limit=500
            )
            
            df = pd.DataFrame(candles, columns=[
                "open_time", "open", "high", "low", "close",
                "volume", "close_time", "quote_asset_volume", "number_of_trades",
                "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "--"
            ])
            
            df = df[["open", "high", "low", "close", "volume", "open_time"]]
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col])
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms").dt.tz_localize("UTC")
            df["open_time"] = df["open_time"].dt.tz_convert("America/Sao_Paulo")
            
            return df
        except Exception as e:
            trade_logger.log_error("Erro ao buscar dados do ativo", e)
            raise

    
    def buyStock(self) -> Optional[Dict[str, Any]]:
        """
        Executa ordem de compra no mercado.
        
        Fluxo:
        1. Valida quantidade
        2. Executa ordem de mercado
        3. Atualiza posição
        4. Envia alertas/logs
        
        Returns:
            Optional[Dict[str, Any]]: Dicionário com detalhes da ordem executada ou None em caso de falha
            
        Raises:
            BinanceAPIException: Em caso de erro na API da Binance
            ValueError: Se a quantidade negociada for inválida
        """
        if not self.actual_trade_position:
            try:
                quantity = self._calculate_buy_quantity()
                self._validate_trade_quantity(quantity)
                order = self._execute_market_order(SIDE_BUY, quantity)
                self._update_position_after_trade(True)
                self._send_trade_alert("COMPRA", order)
                return order
            except BinanceAPIException as e:
                self._handle_trade_error("compra", e)
                return None
        return None

    def sellStock(self) -> Optional[Dict[str, Any]]:
        """
        Executa ordem de venda no mercado.
        
        Fluxo:
        1. Calcula quantidade disponível
        2. Valida quantidade
        3. Executa ordem de mercado
        4. Atualiza posição
        5. Envia alertas/logs
        
        Returns:
            Optional[Dict[str, Any]]: Dicionário com detalhes da ordem executada ou None em caso de falha
            
        Raises:
            BinanceAPIException: Em caso de erro na API da Binance
            ValueError: Se a quantidade negociada for inválida
        """
        if self.actual_trade_position:
            try:
                quantity = self._calculate_sell_quantity()
                self._validate_trade_quantity(quantity)
                order = self._execute_market_order(SIDE_SELL, quantity)
                self._update_position_after_trade(False)
                self._send_trade_alert("VENDA", order)
                return order
            except BinanceAPIException as e:
                self._handle_trade_error("venda", e)
                return None
        return None

    def _execute_market_order(self, side: str, quantity: float) -> Dict[str, Any]:
        """Executa uma ordem de mercado"""
        order = self.client_binance.create_order(
            symbol=self.operation_code,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=quantity
        )
        self.createLogOrder(order)
        trade_logger.log_info(f"Ordem de {side} executada: {order['orderId']}")
        return order

    def _update_position_after_trade(self, new_position: bool) -> None:
        """Atualiza o estado da posição após uma trade"""
        self.actual_trade_position = new_position
        self.updateAllData()

    def _calculate_buy_quantity(self) -> float:
        """Calcula a quantidade a ser comprada"""
        usdt_balance = 0.0
        for balance in self.account_data["balances"]:
            if balance["asset"] == self.config.quote_asset:
                usdt_balance = float(balance["free"])
                break
        btc_price = float(self.client_binance.get_symbol_ticker(symbol=self.operation_code)['price'])
        quantity = (usdt_balance * (self.traded_percentage / 100)) / btc_price
        return round(quantity, 5)

    def _calculate_sell_quantity(self) -> float:
        """Calcula a quantidade a ser vendida"""
        return int(self.last_stock_account_balance * 1000) / 1000

    def _validate_trade_quantity(self, quantity: float) -> None:
        """Valida a quantidade a ser negociada"""
        if quantity <= 0:
            raise ValueError("Quantidade de trade inválida")

    def _handle_trade_error(self, trade_type: str, error: Exception) -> None:
        """Trata erros durante execução de trades"""
        trade_logger.log_error(f"Erro ao executar ordem de {trade_type}", error)
        self._send_error_alert(trade_type, str(error))

    def _send_trade_alert(self, trade_type: str, order: Dict[str, Any]) -> None:
        """Envia alerta sobre trade executado"""
        message = f"{trade_type} executada: {order['orderId']} - {order['origQty']} {self.stock_code}"
        trade_logger.log_info(message)
        print(message)
        # Aqui poderia ser integrado com serviço de notificações (email, SMS, etc)

    def _send_error_alert(self, trade_type: str, error_message: str) -> None:
        """Envia alerta sobre erro em trade"""
        message = f"ERRO em {trade_type}: {error_message}"
        trade_logger.log_error(message)
        print(message)
        # Aqui poderia ser integrado com serviço de notificações (email, SMS, etc)
    
    def createLogOrder(self, order):
        """Cria log da ordem executada"""
        try:
            timestamp = order.get('transactTime', int(time.time() * 1000))
            datetime_transact = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')
            
            log_message = (
                f"\nORDEM EXECUTADA:\n"
                f"ID: {order['orderId']}\n"
                f"Side: {order['side']}\n"
                f"Symbol: {order['symbol']}\n"
                f"Quantity: {order['origQty']}\n"
                f"Price: {order.get('price', 'MARKET')}\n"
                f"Status: {order['status']}\n"
                f"Time: {datetime_transact}\n"
            )
            
            trade_logger.log_info(log_message)
            print(log_message)
            
        except Exception as e:
            trade_logger.log_error("Erro ao criar log da ordem", e)


    def start(self):
        """Inicia a execução contínua do bot"""
        if not self._running:
            self._running = True
            trade_logger.log_info("Bot iniciado")
            self._run_loop()

    def stop(self):
        """Para a execução do bot de forma segura"""
        if self._running:
            self._running = False
            trade_logger.log_info("Bot parado")
            # Fecha qualquer posição aberta
            if self.actual_trade_position:
                self.sellStock()
            self.updateAllData()

    def _run_loop(self):
        """Loop principal de execução do bot"""
        while self._running:
            try:
                self.updateAllData()
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Log do status atual
                status_msg = (
                    f"\n{'='*50}"
                    f"\nStatus do Bot em {current_time}"
                    f"\nPosição atual: {'Comprado' if self.actual_trade_position else 'Vendido'}"
                    f"\nBalanço atual: {self.last_stock_account_balance} {self.stock_code}"
                    f"\nPreço atual: {self.candle_data['close'].iloc[-1]:.2f}"
                )
                trade_logger.log_info(status_msg)
                
                # Calcula indicadores
                df_with_indicators = calculate_indicators(self.candle_data)
                
                # Gera sinais de trading
                signals = strategy_signals(df_with_indicators)
                
                # Último sinal gerado
                trade_decision = signals.iloc[-1] == 1
                
                # Log da análise técnica
                analysis_msg = (
                    f"\nAnálise Técnica:"
                    f"\nEMA 7: {df_with_indicators['ema_7'].iloc[-1]:.2f}"
                    f"\nEMA 25: {df_with_indicators['ema_25'].iloc[-1]:.2f}"
                    f"\nMACD: {df_with_indicators['macd_line'].iloc[-1]:.2f}"
                    f"\nSinal MACD: {df_with_indicators['signal_line'].iloc[-1]:.2f}"
                    f"\nRSI: {df_with_indicators['rsi'].iloc[-1]:.2f}"
                    f"\nSinal gerado: {'COMPRA' if trade_decision else 'VENDA'}"
                )
                trade_logger.log_info(analysis_msg)
                
                if not self.actual_trade_position and trade_decision:
                    self.buyStock()
                elif self.actual_trade_position and not trade_decision:
                    self.sellStock()
                    
                time.sleep(2)
                self.updateAllData()
                
            except Exception as e:
                trade_logger.log_error("Erro durante execução", e)
                time.sleep(10)  # Reduzido para 10 segundos antes de tentar novamente

    def execute(self):
        """Executa um único ciclo de trading"""
        if self._running:
            self._run_loop()

def main():
    try:
        # Carrega configurações do ambiente
        config = TradingConfig.from_env()
        
        # Inicializa o cliente Binance para verificar conexão
        client = Client(config.api_key, config.secret_key)
        
        # Obtém o preço atual do ativo
        ticker = client.get_symbol_ticker(symbol=config.trading_pair)
        current_price = float(ticker['price'])
        
        # Obtém o saldo da moeda base
        account = client.get_account()
        base_balance = 0.0
        for balance in account['balances']:
            if balance['asset'] == config.quote_asset:
                base_balance = float(balance['free'])
                break
        
        trade_logger.log_info(f"Saldo {config.quote_asset}: {base_balance}, Preço {config.trading_pair}: {current_price}")
        
        # Inicializa o bot
        trader = BinanceTraderBot(config)
        
        
        while True:
            trader.execute()
            time.sleep(60)
            
    except KeyboardInterrupt:
        trade_logger.log_info("Programa encerrado pelo usuário")
    except Exception as e:
        trade_logger.log_error("Erro fatal", e)
        

if __name__ == "__main__":
    main()
