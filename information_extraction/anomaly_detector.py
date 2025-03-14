# anomaly_detector.py
import logging
import datetime
import pytz
import re
from typing import List, Optional, Dict, Any
from .schemas import Entity, EntityLabel
from datetime import timedelta
from dataclasses import dataclass

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@dataclass
class Anomaly:
    """异常类"""
    type: str
    description: str
    severity: float
    related_entities: List[Entity]
    timestamp: datetime
    details: Optional[Dict[str, Any]] = None

class FraudDetector:
    timezone_map = {
        "New York": "America/New_York",
        "London": "Europe/London",
        "Tokyo": "Asia/Tokyo",
        "Singapore": "Asia/Singapore",
        "Beijing": "Asia/Shanghai",
        "Shanghai": "Asia/Shanghai",
        "Hong Kong": "Asia/Hong_Kong"
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.threshold_amount = 100000  # 大额交易阈值
        self.frequency_threshold = 5    # 频繁交易阈值
        self.time_window = timedelta(hours=24)  # 时间窗口
        
        # 可疑交易模式
        self.suspicious_patterns = [
            r'多笔.*?转账',
            r'可疑.*?交易',
            r'未经授权',
            r'异常.*?操作'
        ]
        
    @staticmethod
    def detect_time_anomalies(entities: List[Entity], text: str, timezone_mapping: Optional[dict] = None) -> List[Anomaly]:
        anomalies = []
        time_entities = [e for e in entities if e.label == "DATE"]
        location_entities = [e for e in entities if e.label == "GEO"]

        timezone_mapping = timezone_mapping or FraudDetector.timezone_map

        for time_ent in time_entities:
            time_str = time_ent.text
            parsed_time = FraudDetector.parse_time(time_str)
            if not parsed_time:
                continue

            for loc_ent in location_entities:
                location = loc_ent.text
                if location not in timezone_mapping:
                    continue
                try:
                    tz = pytz.timezone(timezone_mapping[location])
                    local_time = parsed_time.astimezone(tz)
                    if not (9 <= local_time.hour <= 17):
                        anomaly_desc = f"非工作时间交易：{time_str} @ {location} (当地时间 {local_time.strftime('%Y-%m-%d %H:%M')})"
                        anomalies.append(Anomaly(
                            type="TIME_ANOMALY",
                            description=anomaly_desc,
                            severity=0.85,
                            related_entities=[time_ent, loc_ent],
                            timestamp=datetime.datetime.now()
                        ))
                except pytz.exceptions.UnknownTimeZoneError:
                    logging.error(f"未知时区配置: {location}")

        return anomalies
    
    @staticmethod
    def parse_time(time_str: str) -> Optional[datetime.datetime]:
        """解析各种格式的时间字符串"""
        # 支持多种时间格式
        formats = [
            "%Y-%m-%dT%H:%M",       # ISO 8601
            "%Y-%m-%d %H:%M",       # 标准日期时间
            "%Y/%m/%d %H:%M",       # 斜杠分隔的日期时间
            "%d-%b-%Y %H:%M",       # 日-月名-年 时间
            "%Y-%m-%d",             # 标准日期
            "%Y/%m/%d",             # 斜杠分隔的日期
            "%Y年%m月%d日",          # 中文日期
            "%m月%d日",              # 中文月日
            "%Y/%m",                # 年/月
            "%Y年%m月",              # 中文年月
            "%d/%m/%Y",             # 日/月/年
            "%m/%d/%Y",             # 月/日/年
            "%Y.%m.%d",             # 点分隔的日期
        ]
        
        # 预处理时间字符串
        time_str = time_str.strip()
        
        # 处理特殊格式：2023/4/11 -> 2023/04/11
        if re.match(r'\d{4}/\d{1,2}/\d{1,2}', time_str):
            parts = time_str.split('/')
            if len(parts) == 3:
                time_str = f"{parts[0]}/{int(parts[1]):02d}/{int(parts[2]):02d}"
        
        # 尝试各种格式解析
        for fmt in formats:
            try:
                parsed_time = datetime.datetime.strptime(time_str, fmt)
                # 如果没有时间部分，设置为当天的中午
                if fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%m月%d日", "%Y/%m", "%Y年%m月", "%d/%m/%Y", "%m/%d/%Y", "%Y.%m.%d"]:
                    parsed_time = parsed_time.replace(hour=12, tzinfo=datetime.timezone.utc)
                return parsed_time
            except ValueError:
                continue
        
        # 尝试解析更复杂的格式
        try:
            # 处理 "2023/4/11" 这样的格式
            if re.match(r'\d{4}/\d{1,2}/\d{1,2}', time_str):
                year, month, day = map(int, time_str.split('/'))
                return datetime.datetime(year, month, day, 12, 0, tzinfo=datetime.timezone.utc)
            
            # 处理 "3月4日" 这样的格式
            match = re.match(r'(\d{1,2})月(\d{1,2})日', time_str)
            if match:
                month, day = map(int, match.groups())
                current_year = datetime.datetime.now().year
                return datetime.datetime(current_year, month, day, 12, 0, tzinfo=datetime.timezone.utc)
            
            # 处理 "2025年3月10日" 这样的格式
            match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', time_str)
            if match:
                year, month, day = map(int, match.groups())
                return datetime.datetime(year, month, day, 12, 0, tzinfo=datetime.timezone.utc)
        except (ValueError, TypeError) as e:
            logging.warning(f"复杂时间格式解析失败: {time_str}, 错误: {str(e)}")
        
        logging.warning(f"时间格式无法解析: {time_str}")
        return None

    @staticmethod
    def extract_entities_from_text(text: str) -> List[Entity]:
        entities = []
        # 增强日期识别
        date_patterns = [
            r'\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:T\d{1,2}:\d{1,2})?',  # 2023-04-01, 2023/4/1
            r'\d{1,2}月\d{1,2}日',                                # 3月4日
            r'\d{4}年\d{1,2}月\d{1,2}日',                         # 2025年3月10日
            r'\d{4}年\d{1,2}月',                                 # 2023年4月
            r'\d{4}\.\d{1,2}\.\d{1,2}'                           # 2023.04.01
        ]
        
        for pattern in date_patterns:
            dates = re.finditer(pattern, text)
            for match in dates:
                entities.append(Entity(
                    label="DATE",
                    text=match.group(),
                    start=match.start(),
                    end=match.end()
                ))
        
        # 扩展地点识别
        locations = re.finditer(r'\b(北京|上海|广州|深圳|香港|New York|London|Tokyo|Singapore|Hong Kong)\b', text, re.IGNORECASE)
        for match in locations:
            entities.append(Entity(
                label="GEO",
                text=match.group().title(),
                start=match.start(),
                end=match.end()
            ))
        return entities

    def detect_anomalies(self, entities: List[Entity], text: str) -> List[Anomaly]:
        """检测异常"""
        anomalies = []
        
        # 提取金额和账户实体
        amounts = [e for e in entities if e.type == EntityLabel.MONEY.value]
        accounts = [e for e in entities if e.type in [EntityLabel.ACCOUNT.value, EntityLabel.BANK.value]]
        dates = [e for e in entities if e.type == EntityLabel.DATE.value]
        
        # 检测大额交易
        for amount in amounts:
            try:
                value = float(re.sub(r'[^\d.]', '', amount.text))
                if value > self.threshold_amount:
                    anomalies.append(Anomaly(
                        type="LARGE_TRANSACTION",
                        description=f"发现大额交易: {amount.text}",
                        severity=0.7,
                        related_entities=[amount],
                        timestamp=datetime.datetime.now()
                    ))
            except ValueError:
                continue
        
        # 检测可疑模式
        for pattern in self.suspicious_patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                # 获取上下文
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context = text[start:end]
                
                # 查找相关实体
                related = []
                for entity in entities:
                    if start <= entity.start <= end or start <= entity.end <= end:
                        related.append(entity)
                
                if related:
                    anomalies.append(Anomaly(
                        type="SUSPICIOUS_PATTERN",
                        description=f"发现可疑交易模式: {match.group()}",
                        severity=0.6,
                        related_entities=related,
                        timestamp=datetime.datetime.now()
                    ))
        
        return anomalies

class AnomalyDetector:
    def __init__(self):
        self.fraud_detector = FraudDetector()

    def process_chunk(self, chunk: str) -> List[Anomaly]:
        """
        处理文本块，提取实体并检测时间异常
        """
        entities = self.fraud_detector.extract_entities_from_text(chunk)
        anomalies = self.fraud_detector.detect_time_anomalies(entities, chunk)
        return anomalies