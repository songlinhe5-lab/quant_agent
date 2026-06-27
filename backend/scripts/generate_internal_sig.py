"""
内部通信 HMAC 签名生成工具
用于生成 X-Internal-Sig 签名头
"""
import sys
import os

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.security import generate_internal_signature
from core.config import settings


def main():
    if len(sys.argv) < 3:
        print("使用方法: python generate_internal_sig.py <method> <path>")
        print("示例: python generate_internal_sig.py GET /api/v1/internal/health")
        sys.exit(1)
    
    method = sys.argv[1]
    path = sys.argv[2]
    
    signature = generate_internal_signature(method, path)
    print(f"Method: {method}")
    print(f"Path: {path}")
    print(f"Signature: {signature}")
    print(f"\n在请求头中添加:")
    print(f"X-Internal-Sig: {signature}")


if __name__ == "__main__":
    main()
