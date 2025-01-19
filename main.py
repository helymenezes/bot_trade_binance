import os 
import time
from datetime  import datetime
import logging
import pandas as pd
from binance.client import Client
from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_TYPE_MARKET
from binance.exceptions import BinanceAPIException
from logger import *


#Configurar logging
logging.basicConfig(
    filename='historico_trades.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

#Configurar API

class BinanceTraderBot:
    def __init__(self, stock_code, operation_code, traded_quantity, traded_percentage, candle_period):
        self.stock_code = stock_code
        self.operation_code = operation_code
        self.traded_quantity = traded_quantity
        self.traded_percentage = traded_percentage
        self.candle_period = candle_period
        self.actual_trade_position = False
        
        # Inicialização das credenciais
        self.api_key = os.getenv('BINANCE_API_KEY')
        self.secret_key = os.getenv('BINANCE_SECRET_KEY')
        
        if not self.api_key or not self.secret_key:
            raise ValueError("API Key ou Secret Key não encontradas nas variáveis de ambiente")
            
        try:
            self.client_binance = Client( self.api_key, self.secret_key, tld='com')
            self.updateAllData()
            logging.info("Robô Trader iniciado com sucesso")
            print("Robô Trader iniciado...")
        except BinanceAPIException as e:
            logging.error("Erro ao inicializar o cliente Binance: %s", str(e))
            raise

    def updateAllData(self):
        """Atualiza todos os dados da conta"""
        try:
            self.account_data = self.getUpdatedAccountData()
            self.last_stock_account_balance = self.getLastStockAccountBalance()
            self.actual_trade_position = self.getActualTradePosition()
            self.candle_data = self.getStockData_ClosePrice_OpenTime()
        except Exception as e:
            logging.error("Erro ao atualizar dados: %s", str(e))
            raise

    def getUpdatedAccountData(self):
        """Busca informações atualizadas da conta Binance"""
        return self.client_binance.get_account()

    def getLastStockAccountBalance(self):
        """Busca o último balanço da conta na stock escolhida"""
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
            
            df = df[["open", "high", "low", "close", "open_time"]]
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col])
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms").dt.tz_localize("UTC")
            df["open_time"] = df["open_time"].dt.tz_convert("America/Sao_Paulo")
            
            return df
        except Exception as e:
            logging.error("Erro ao buscar dados do ativo: %s", str(e))
            raise

    def getMovingAverageTradeStrategy(self):
        """Executa a estratégia de EMA"""
        try:
            df = self.candle_data.copy()
            
            # Calcula as EMAs
            df['ema_7'] = df['close'].ewm(span=7, adjust=False).mean()
            df['ema_25'] = df['close'].ewm(span=25, adjust=False).mean()
            df['ema_99'] = df['close'].ewm(span=99, adjust=False).mean()
            
            # Obtém os últimos valores
            last_ema_7 = df['ema_7'].iloc[-1]
            last_ema_25 = df['ema_25'].iloc[-1]
            last_ema_99 = df['ema_99'].iloc[-1]
            
            # Lógica de decisão
            if last_ema_7 > last_ema_25 and last_ema_7 > last_ema_99:
                trade_decision = True  # Compra
            elif last_ema_7 < last_ema_25 and last_ema_7 > last_ema_99:
                trade_decision = False  # Venda
            else:
                trade_decision = None  # Manter posição
            
            logging.info(
                "Estratégia EMA: 7=%.3f, 25=%.3f, 99=%.3f, decisão=%s",
                last_ema_7, last_ema_25, last_ema_99,
                'Comprar' if trade_decision else 'Vender' if trade_decision is not None else 'Manter'
            )
            
            return trade_decision
        except Exception as e:
            logging.error("Erro ao executar estratégia: %s", str(e))
            raise

    def buyStock(self):
        """Executa ordem de compra"""
        if not self.actual_trade_position:
            try:
                order = self.client_binance.create_order(
                    symbol=self.operation_code,
                    side=SIDE_BUY,
                    type=ORDER_TYPE_MARKET,
                    quantity=self.traded_quantity
                )
                self.actual_trade_position = True
                self.createLogOrder(order)
                logging.info("Ordem de compra executada: %s", order['orderId'])
                return order
            except BinanceAPIException as e:
                logging.error("Erro ao executar ordem de compra: %s", str(e))
                return False
        return False

    def sellStock(self):
        """Executa ordem de venda"""
        if self.actual_trade_position:
            try:
                quantity = int(self.last_stock_account_balance * 1000) / 1000
                order = self.client_binance.create_order(
                    symbol=self.operation_code,
                    side=SIDE_SELL,
                    type=ORDER_TYPE_MARKET,
                    quantity=quantity
                )
                self.actual_trade_position = False
                self.createLogOrder(order)
                logging.info(f"Ordem de venda executada: {order['orderId']}")
                return order
            except BinanceAPIException as e:
                logging.error(f"Erro ao executar ordem de venda: {str(e)}")
                return False
        return False
    
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
            
            logging.info(log_message)
            print(log_message)
            
        except Exception as e:
            logging.error(f"Erro ao criar log da ordem: {str(e)}")

    def execute(self):
        """Executa o ciclo principal de trading"""
        try:
            self.updateAllData()
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            print(f"\nExecutado: {current_time}")
            print(f"Posição atual: {'Comprado' if self.actual_trade_position else 'Vendido'}")
            print(f"Balanço atual: {self.last_stock_account_balance} ({self.stock_code})")
            
            trade_decision = self.getMovingAverageTradeStrategy()
            
            if not self.actual_trade_position and trade_decision:
                self.buyStock()
            elif self.actual_trade_position and not trade_decision:
                self.sellStock()
                
            time.sleep(2)
            self.updateAllData()
            
        except Exception as e:
            logging.error(f"Erro durante execução: {str(e)}")
            time.sleep(60)  # Espera 1 minuto antes de tentar novamente

def main():
    # Configurações
    STOCK_CODE = "BTC"#SOL
    OPERATION_CODE = "BTCUSDT"
    CANDLE_PERIOD = Client.KLINE_INTERVAL_1HOUR
    TRADED_QUANTITY = 10
    
    try:
        trader = BinanceTraderBot(
            STOCK_CODE,
            OPERATION_CODE,
            TRADED_QUANTITY,
            100,
            CANDLE_PERIOD
        )
        
        while True:
            trader.execute()
            time.sleep(60)
            
    except KeyboardInterrupt:
        logging.info("Programa encerrado pelo usuário")
    except Exception as e:
        logging.error("Erro fatal: %s", str(e))
        

if __name__ == "__main__":
    main()
