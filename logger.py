import logging
import json
from datetime import datetime
from pathlib import Path

class TradeLogger:
    def __init__(self, log_dir="src/logs"):
        """
        Inicializa o logger com configurações personalizadas
        
        Args:
            log_dir (str): Diretório onde os logs serão salvos
        """
        # Cria o diretório de logs se não existir
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Configura o logger principal
        self.logger = self._setup_logger()
        
    def _setup_logger(self):
        """Configura e retorna o logger com as configurações desejadas"""
        logger = logging.getLogger('TradeBot')
        logger.setLevel(logging.INFO)
        
        # Evita duplicação de handlers
        if not logger.handlers:
            # Handler para arquivo
            file_handler = logging.FileHandler(
                self.log_dir / "trading_bot.log",
                encoding='utf-8'
            )
            file_handler.setLevel(logging.INFO)
            
            # Handler para console
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # Formato do log
            formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            logger.addHandler(file_handler)
            logger.addHandler(console_handler)
        
        return logger
    
    def _format_timestamp(self, timestamp_ms):
        """
        Converte timestamp em milissegundos para formato legível
        
        Args:
            timestamp_ms (int): Timestamp em milissegundos
            
        Returns:
            str: Data e hora formatada
        """
        try:
            return datetime.utcfromtimestamp(
                timestamp_ms / 1000
            ).strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            self.logger.error(f"Erro ao formatar timestamp: {e}")
            return "Timestamp inválido"
    
    def _extract_order_details(self, order):
        """
        Extrai detalhes relevantes da ordem
        
        Args:
            order (dict): Objeto de ordem da Binance
            
        Returns:
            dict: Detalhes formatados da ordem
        """
        try:
            return {
                'side': order.get('side'),
                'type': order.get('type'),
                'quantity': order.get('executedQty'),
                'asset': order.get('symbol'),
                'price_per_unit': order.get('fills', [{}])[0].get('price'),
                'currency': order.get('fills', [{}])[0].get('commissionAsset'),
                'total_value': order.get('cumulativeQuoteQty'),
                'timestamp': order.get('transactTime'),
                'order_id': order.get('orderId'),
                'status': order.get('status')
            }
        except Exception as e:
            self.logger.error(f"Erro ao extrair detalhes da ordem: {e}")
            return {}

    def log_order(self, order):
        """
        Registra uma ordem de trading nos logs
        
        Args:
            order (dict): Objeto de ordem da Binance
        """
        try:
            # Extrai detalhes da ordem
            details = self._extract_order_details(order)
            if not details:
                self.logger.error("Falha ao processar detalhes da ordem")
                return
            
            # Formata a data/hora
            datetime_transact = self._format_timestamp(details['timestamp'])
            
            # Cria mensagem de log detalhada
            log_message = (
                f"\nORDEM EXECUTADA:"
                f"\nID: {details['order_id']}"
                f"\nStatus: {details['status']}"
                f"\nSide: {details['side']}"
                f"\nAtivo: {details['asset']}"
                f"\nQuantidade: {details['quantity']}"
                f"\nPreço unitário: {details['price_per_unit']}"
                f"\nMoeda: {details['currency']}"
                f"\nValor total: {details['total_value']}"
                f"\nTipo: {details['type']}"
                f"\nData/Hora: {datetime_transact}"
                f"\n"
            )
            
            # Registra no log e exibe no console
            self.logger.info(log_message)
            
            # Salva ordem completa em arquivo separado para referência
            self._save_complete_order(order, details['order_id'])
            
        except Exception as e:
            self.logger.error(f"Erro ao registrar ordem: {e}")
    
    def _save_complete_order(self, order, order_id):
        """
        Salva os detalhes completos da ordem em um arquivo JSON separado
        
        Args:
            order (dict): Objeto completo da ordem
            order_id (str): ID da ordem
        """
        try:
            order_file = self.log_dir / f"order_{order_id}.json"
            with open(order_file, 'w', encoding='utf-8') as f:
                json.dump(order, f, indent=2)
        except Exception as e:
            self.logger.error(f"Erro ao salvar detalhes completos da ordem: {e}")
    
    def log_error(self, message, exception=None):
        """
        Registra erros com detalhes adicionais
        
        Args:
            message (str): Mensagem de erro
            exception (Exception, optional): Objeto de exceção
        """
        error_msg = f"{message}"
        if exception:
            error_msg += f": {str(exception)}"
        self.logger.error(error_msg)
    
    def log_info(self, message):
        """
        Registra mensagens informativas
        
        Args:
            message (str): Mensagem a ser registrada
        """
        self.logger.info(message)

# Instância global do logger
trade_logger = TradeLogger()

# Função de compatibilidade com o código anterior
def createLogOrder(order):
    """
    Função de compatibilidade para manter a interface anterior
    
    Args:
        order (dict): Objeto de ordem da Binance
    """
    trade_logger.log_order(order)