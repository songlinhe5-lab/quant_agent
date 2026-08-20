"""download_report 域名白名单校验测试。"""

import pytest

from hermes_agent.tools.download_report_tool import _is_allowed_url


class TestAllowedDomains:
    @pytest.mark.parametrize(
        "url",
        [
            # 港股披露易
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0422/2026042200668.pdf",
            "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0422/x.pdf",
            # 美股 SEC
            "https://www.sec.gov/Archives/edgar/data/320193/000032019325000001/a2025q1.pdf",
            # A股/研报 dfcfw (东方财富研报 PDF 静态域)
            "https://pdf.dfcfw.com/HK_00772_2026042200.pdf",
            "https://pdf.dfcfw.com/pdf/H3_AP2026082000_1.pdf",
            # 巨潮/上交所
            "https://static.cninfo.com.cn/finalpage/2026-08-20/1223.PDF",
        ],
    )
    def test_allowed(self, url):
        assert _is_allowed_url(url) is True, f"应允许: {url}"

    @pytest.mark.parametrize(
        "url",
        [
            # 未在白名单的域名
            "https://evil.com/steal.pdf",
            "https://not-exist.example.com/x.pdf",
            # 白名单域名的伪装 (子域名混淆不应放行)
            "https://hkexnews.hk.evil.com/x.pdf",
            "https://notdfcfw.com/x.pdf",
        ],
    )
    def test_denied(self, url):
        assert _is_allowed_url(url) is False, f"应拒绝: {url}"
