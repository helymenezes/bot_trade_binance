import os
import re
import time
from datetime import datetime
import pandas as pd
from typing import Dict, Any, Optional, Union
from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_TYPE_MARKET
from binance.exceptions import BinanceAPIException
from binance import Client
from dotenv import load_dotenv
from logger import trade_logger
from dataclasses import dataclass
from src.indicators import calculate_indicators, strategy_signals
from src.monitor import BotMonitor
from decimal import Decimal, ROUND_DOWN

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

class BinanceTraderBot:
    """Classe principal do bot de trading para a Binance."""
    
    def __init__(self, config: TradingConfig):
        self.config = config
        self.stock_code = config.base_asset
        self.operation_code = config.trading_pair
        self.traded_percentage = config.trading_percentage
        self.candle_period = config.candle_interval
        self.stop_loss = config.stop_loss
        self.take_profit = config.take_profit
        self.traded_quantity = Decimal("0")
        
        self.actual_trade_position = False
        self._running = False
        self.initial_balance = Decimal("0")
        
        self.account_data = None
        self.last_stock_account_balance = Decimal("0")
        self.candle_data = None
        self.last_trade = None
        self.monitor = BotMonitor(trade_logger)
        
        if not self.config.api_key or not self.config.secret_key:
            raise ValueError("API Key ou Secret Key não encontradas nas variáveis de ambiente")
            
        try:
            # Inicializa o cliente Binance
            self.client_binance = Client(
                self.config.api_key,
                self.config.secret_key,
                tld='com'
            )
            self.client_binance.session.headers.update({
                'Connection': 'keep-alive',
                'Keep-Alive': '30'
            })
            
            # Testa a conexão com retry
            max_retries = 5
            retry_delay = 10
            for attempt in range(max_retries):
                try:
                    self.client_binance.ping()
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
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
        max_retries = 5
        retry_delay = 10
        
        for attempt in range(max_retries):
            try:
                self.client_binance.ping()
                
                self.account_data = self.getUpdatedAccountData()
                self.last_stock_account_balance = self.getLastStockAccountBalance()
                self.actual_trade_position = self.getActualTradePosition()
                self.candle_data = self.getStockData_ClosePrice_OpenTime()
                
                # Atualiza a quantidade a ser negociada se não estiver em posição
                if not self.actual_trade_position:
                    usdt_balance = Decimal("0")
                    for balance in self.account_data["balances"]:
                        if balance["asset"] == self.config.quote_asset:
                            usdt_balance = Decimal(balance["free"])
                            break
                    btc_price = Decimal(self.client_binance.get_symbol_ticker(symbol=self.operation_code)['price'])
                    self.traded_quantity = (usdt_balance * (Decimal(self.traded_percentage) / Decimal("100"))) / btc_price
                
                if self.initial_balance == Decimal("0") and self.last_stock_account_balance > Decimal("0"):
                    self.initial_balance = self.last_stock_account_balance
                    trade_logger.log_info(f"Saldo inicial definido: {self.initial_balance}")
                
                # Verifica stop loss e take profit se estiver em posição
                if self.actual_trade_position and len(self.candle_data) > 0:
                    current_price = self.candle_data['close'].iloc[-1]
                    entry_price = self.candle_data['close'].iloc[-2]
                    price_change = ((float(current_price) - float(entry_price)) / float(entry_price)) * 100
                    if price_change <= -self.stop_loss:
                        trade_logger.log_info(f"Stop loss atingido: {price_change:.2f}%")
                        self.sellStock()
                    if price_change >= self.take_profit:
                        trade_logger.log_info(f"Take profit atingido: {price_change:.2f}%")
                        self.sellStock()
                
                return
                
            except BinanceAPIException as e:
                if attempt < max_retries - 1:
                    trade_logger.log_info(f"Tentativa {attempt + 1} falhou. Tentando novamente em {retry_delay} segundos...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    trade_logger.log_error("Erro ao atualizar dados após várias tentativas", e)
                    raise
            except Exception as e:
                trade_logger.log_error("Erro ao atualizar dados", e)
                raise

    def getUpdatedAccountData(self):
        return self.client_binance.get_account()

    def getLastStockAccountBalance(self):
        if self.account_data and "balances" in self.account_data:
            for stock in self.account_data["balances"]:
                if stock["asset"] == self.stock_code:
                    return Decimal(stock["free"])
        return Decimal("0")

    def getActualTradePosition(self):
        return self.last_stock_account_balance > Decimal("0.001")

    def getStockData_ClosePrice_OpenTime(self):
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
        if not self.actual_trade_position:
            try:
                # Calcula quantidade otimizada utilizando Decimal para precisão
                quantity = self._calculate_buy_quantity()
                self._validate_trade_quantity(quantity)
                order = self.client_binance.create_order(
                    symbol=self.operation_code,
                    side=SIDE_BUY,
                    type=ORDER_TYPE_MARKET,
                    quantity=quantity  # A quantidade já está formatada (string)
                )
                self.actual_trade_position = True
                self.createLogOrder(order)
                trade_logger.log_info(f"Ordem de compra executada: {order['orderId']}")
                return order
            except BinanceAPIException as e:
                trade_logger.log_error(f"Erro ao executar ordem de compra: {str(e)}")
                return None
            except ValueError as e:
                trade_logger.log_error(f"Erro de validação na ordem de compra: {str(e)}")
                return None
        return None

    def sellStock(self) -> Optional[Dict[str, Any]]:
        if self.actual_trade_position:
            try:
                # Calcula quantidade de venda utilizando Decimal para precisão
                quantity = self._calculate_sell_quantity()
                self._validate_trade_quantity(quantity)
                order = self.client_binance.create_order(
                    symbol=self.operation_code,
                    side=SIDE_SELL,
                    type=ORDER_TYPE_MARKET,
                    quantity=quantity  # A quantidade já está formatada (string)
                )
                self.actual_trade_position = False
                self.createLogOrder(order)
                trade_logger.log_info(f"Ordem de venda executada: {order['orderId']}")
                return order
            except BinanceAPIException as e:
                trade_logger.log_error(f"Erro ao executar ordem de venda: {str(e)}")
                return None
            except ValueError as e:
                trade_logger.log_error(f"Erro de validação na ordem de venda: {str(e)}")
                return None
        return None

    def _execute_market_order(self, side: str, quantity: Union[str, Decimal]) -> Dict[str, Any]:
        order = self.client_binance.create_order(
            symbol=self.operation_code,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=str(quantity)
        )
        self.createLogOrder(order)
        trade_logger.log_info(f"Ordem de {side} executada: {order['orderId']}")
        return order

    def _update_position_after_trade(self, new_position: bool) -> None:
        self.actual_trade_position = new_position
        self.updateAllData()

    def get_symbol_info(self):
        exchange_info = self.client_binance.get_exchange_info()
        for symbol_info in exchange_info['symbols']:
            if symbol_info['symbol'] == self.operation_code:
                return symbol_info
        return None

    def _calculate_buy_quantity(self) -> str:
        """
        Calcula a quantidade a ser comprada utilizando o módulo Decimal para arredondar
        corretamente de acordo com as regras do par (LOT_SIZE).
        """
        # Busca saldo da moeda de cotação
        usdt_balance = Decimal("0")
        for balance in self.account_data["balances"]:
            if balance["asset"] == self.config.quote_asset:
                usdt_balance = Decimal(balance["free"])
                break
        btc_price = Decimal(self.client_binance.get_symbol_ticker(symbol=self.operation_code)['price'])
        raw_quantity = (usdt_balance * (Decimal(self.traded_percentage) / Decimal("100"))) / btc_price

        symbol_info = self.get_symbol_info()
        if not symbol_info:
            raise ValueError(f"Não foi possível obter informações do par {self.operation_code}")
        lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
        if not lot_size_filter:
            raise ValueError("Filtro LOT_SIZE não encontrado")
        
        # Converte o step_size e minQty para Decimal e normaliza o step_size
        step_size = Decimal(lot_size_filter['stepSize'])
        min_qty = Decimal(lot_size_filter['minQty'])
        normalized_step_size = step_size.normalize()  # Remove zeros à direita
        # Quantiza utilizando o mesmo expoente do step_size normalizado
        quantity_dec = raw_quantity.quantize(normalized_step_size, rounding=ROUND_DOWN)
        quantity_dec = max(min_qty, quantity_dec)
        decimal_places = abs(normalized_step_size.as_tuple().exponent)
        formatted_quantity = format(quantity_dec, f'.{decimal_places}f')
        
        if not re.match(r'^([0-9]{1,20})(\.[0-9]{1,20})?$', formatted_quantity):
            raise ValueError(f"Quantidade formatada inválida: {formatted_quantity}")
        
        return formatted_quantity

    def _calculate_sell_quantity(self) -> str:
        """
        Calcula a quantidade a ser vendida utilizando o módulo Decimal para arredondar
        corretamente de acordo com as regras do par (LOT_SIZE).
        """
        raw_quantity = self.last_stock_account_balance  # Já é Decimal
        symbol_info = self.get_symbol_info()
        if not symbol_info:
            raise ValueError(f"Não foi possível obter informações do par {self.operation_code}")
        lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
        if not lot_size_filter:
            raise ValueError("Filtro LOT_SIZE não encontrado")
        
        step_size = Decimal(lot_size_filter['stepSize'])
        min_qty = Decimal(lot_size_filter['minQty'])
        normalized_step_size = step_size.normalize()
        quantity_dec = raw_quantity.quantize(normalized_step_size, rounding=ROUND_DOWN)
        quantity_dec = max(min_qty, quantity_dec)
        decimal_places = abs(normalized_step_size.as_tuple().exponent)
        formatted_quantity = format(quantity_dec, f'.{decimal_places}f')
        
        if not re.match(r'^([0-9]{1,20})(\.[0-9]{1,20})?$', formatted_quantity):
            raise ValueError(f"Quantidade formatada inválida: {formatted_quantity}")
        
        return formatted_quantity

    def _validate_trade_quantity(self, quantity: Union[str, Decimal]) -> None:
        """Valida a quantidade a ser negociada considerando as regras do par"""
        qty = Decimal(quantity) if isinstance(quantity, str) else quantity
        if qty <= Decimal("0"):
            raise ValueError("Quantidade de trade inválida")
            
        symbol_info = self.get_symbol_info()
        if not symbol_info:
            raise ValueError(f"Não foi possível obter informações do par {self.operation_code}")
            
        lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
        if lot_size_filter:
            min_qty = Decimal(lot_size_filter['minQty'])
            max_qty = Decimal(lot_size_filter['maxQty'])
            step_size = Decimal(lot_size_filter['stepSize'])
            normalized_step_size = step_size.normalize()
            
            if qty < min_qty:
                raise ValueError(f"Quantidade menor que o mínimo permitido ({min_qty})")
            if qty > max_qty:
                raise ValueError(f"Quantidade maior que o máximo permitido ({max_qty})")
            
            remainder = (qty % normalized_step_size).normalize()
            if remainder != Decimal("0"):
                raise ValueError(f"Quantidade deve ser múltipla de {step_size}")
                
        min_notional_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'MIN_NOTIONAL'), None)
        if min_notional_filter:
            price = Decimal(self.client_binance.get_symbol_ticker(symbol=self.operation_code)['price'])
            notional = qty * price
            min_notional = Decimal(min_notional_filter['minNotional'])
            
            if notional < min_notional:
                raise ValueError(f"Valor total da ordem (quantidade * preço) deve ser maior que {min_notional}")

    def _handle_trade_error(self, trade_type: str, error: Exception) -> None:
        trade_logger.log_error(f"Erro ao executar ordem de {trade_type}", error)
        self._send_error_alert(trade_type, str(error))

    def _send_trade_alert(self, trade_type: str, order: Dict[str, Any]) -> None:
        message = f"{trade_type} executada: {order['orderId']} - {order['origQty']} {self.stock_code}"
        trade_logger.log_info(message)
        print(message)

    def _send_error_alert(self, trade_type: str, error_message: str) -> None:
        message = f"ERRO em {trade_type}: {error_message}"
        trade_logger.log_error(message)
        print(message)

    def createLogOrder(self, order):
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
        if not self._running:
            self._running = True
            trade_logger.log_info("Bot iniciado")
            self._run_loop()

    def stop(self):
        if self._running:
            self._running = False
            trade_logger.log_info("Bot parado")
            if self.actual_trade_position:
                self.sellStock()
            self.updateAllData()

    def _run_loop(self):
        while self._running:
            try:
                self.updateAllData()
                df_with_indicators = calculate_indicators(self.candle_data)
                df_with_indicators['signal'] = strategy_signals(df_with_indicators)
                self.monitor.update_status(self, df_with_indicators)
                trade_decision = df_with_indicators['signal'].iloc[-1] == 1
                if not self.actual_trade_position and trade_decision:
                    order = self.buyStock()
                    if order:
                        self.last_trade = {
                            'side': 'COMPRA',
                            'quantity': order['origQty'],
                            'price': order['fills'][0]['price'],
                            'timestamp': datetime.fromtimestamp(order['transactTime'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                        }
                elif self.actual_trade_position and not trade_decision:
                    order = self.sellStock()
                    if order:
                        self.last_trade = {
                            'side': 'VENDA',
                            'quantity': order['origQty'],
                            'price': order['fills'][0]['price'],
                            'timestamp': datetime.fromtimestamp(order['transactTime'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                        }
                time.sleep(2)
                self.updateAllData()
            except Exception as e:
                trade_logger.log_error("Erro durante execução", e)
                time.sleep(10)

    def execute(self):
        try:
            self.updateAllData()
            df_with_indicators = calculate_indicators(self.candle_data)
            df_with_indicators['signal'] = strategy_signals(df_with_indicators)
            self.monitor.update_status(self, df_with_indicators)
            if not self._running:
                return
            trade_decision = df_with_indicators['signal'].iloc[-1] == 1
            if not self.actual_trade_position and trade_decision:
                order = self.buyStock()
                if order:
                    self.last_trade = {
                        'side': 'COMPRA',
                        'quantity': order['origQty'],
                        'price': order['fills'][0]['price'],
                        'timestamp': datetime.fromtimestamp(order['transactTime'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    }
            elif self.actual_trade_position and not trade_decision:
                order = self.sellStock()
                if order:
                    self.last_trade = {
                        'side': 'VENDA',
                        'quantity': order['origQty'],
                        'price': order['fills'][0]['price'],
                        'timestamp': datetime.fromtimestamp(order['transactTime'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    }
            time.sleep(2)
        except Exception as e:
            trade_logger.log_error("Erro durante execução", e)
            time.sleep(10)

def main():
    try:
        # Carrega configurações do ambiente
        config = TradingConfig.from_env()
        client = Client(config.api_key, config.secret_key)
        ticker = client.get_symbol_ticker(symbol=config.trading_pair)
        current_price = ticker['price']
        account = client.get_account()
        base_balance = "0"
        for balance in account['balances']:
            if balance['asset'] == config.quote_asset:
                base_balance = balance['free']
                break
        trade_logger.log_info(f"Saldo {config.quote_asset}: {base_balance}, Preço {config.trading_pair}: {current_price}")
        trader = BinanceTraderBot(config)
        trader.start()
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            trader.stop()
    except KeyboardInterrupt:
        trade_logger.log_info("Programa encerrado pelo usuário")
    except Exception as e:
        trade_logger.log_error("Erro fatal", e)
        
if __name__ == "__main__":
    main()
