"""Explicit, fail-closed dataset namespaces; no user-supplied filesystem paths."""
from dataclasses import dataclass
from pathlib import Path
import os

CONF = Path(__file__).resolve().parents[1] / 'conf'


@dataclass(frozen=True)
class DataProfile:
    name: str
    conf: Path
    column_collection: str
    metric_collection: str
    meta_database: str | None = None
    dw_database: str | None = None
    value_index: str | None = None

    def public_info(self):
        if self.name == 'retail_ii':
            return {
                'id': self.name, 'name': 'UCI Online Retail II · 真实历史零售数据',
                'coverage': '2009-12-01 至 2011-12-09（首尾年份不完整）',
                'source_url': 'https://archive.ics.uci.edu/dataset/502/online+retail+ii',
                'notice': '金额为英镑 GBP；保留原始重复记录。销售口径排除取消单、非正数量与非正价格；取消金额不代表实际退款。仅支持描述性统计，不证明因果。',
                'examples': ['2010年的销售额和去重订单数是多少？',
                             '按国家统计2011年11月的销售额，取前10名',
                             '2011年11月相比2010年11月，哪些国家贡献了销售额变化？',
                             '将2011年11月相对2010年11月的销售额变化分解为订单数和客单价的贡献'],
            }
        return {'id': self.name, 'name': '原始小样例（虚构数据）',
                'coverage': '2025—2026 示例记录', 'notice': '仅用于功能回归，不代表真实业务表现。',
                'examples': ['统计2026年各地区的成交总额', '2026年各品类的平均订单金额是多少？',
                             '比较2026年与2025年各地区的成交总额']}


def active_profile():
    name = os.environ.get('DATA_AGENT_PROFILE', 'fixture')
    if name == 'fixture':
        return DataProfile(name, CONF, 'data-agent-column', 'data-agent-metric')
    if name == 'retail_ii':
        return DataProfile(name, CONF / name, 'retail-ii-column-v1', 'retail-ii-metric-v1',
                           'meta_retail_ii', 'dw_retail_ii', 'retail-ii-values-v1')
    raise ValueError('UNKNOWN_DATA_PROFILE')
