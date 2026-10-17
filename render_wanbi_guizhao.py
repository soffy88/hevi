#!/usr/bin/env python3
"""
渲染完璧归赵视频
"""

import asyncio
from pathlib import Path
from hevi.tongjian.episodes.wanbi_guizhao import EPISODE
from hevi.tongjian.authored_episode import produce_authored_episode
import os
import os
from openai import AsyncOpenAI

class CallableClient:
    """包装AsyncOpenAI客户端使其可调用"""
    def __init__(self, client):
        self.client = client
    
    async def __call__(self, *args, **kwargs):
        # 根据错误信息，需要提供必要的参数
        # 确保有 'messages' 和 'model' 参数
        if len(args) >= 2:
            # 如果前两个参数是 messages 和 model
            kwargs['messages'] = args[0]
            kwargs['model'] = args[1]
        elif len(args) == 1:
            # 如果只有一个参数，可能是 messages
            if isinstance(args[0], list):
                kwargs['messages'] = args[0]
        
        # 确保有默认模型
        if 'model' not in kwargs:
            kwargs['model'] = 'qwen-max'  # 或者使用适当的默认模型名
            
        return await self.client.chat.completions.create(**kwargs)

async def main():
    # 使用提供的API密钥和端点
    api_key = os.getenv("ALIBABA_MAAS_API_KEY", "sk-ws-H.XEHIPI.VrET.MEUCIGU2g2m8Me6jBWTUN-Yg-zE1qiliJx_6ZLvk0tH3sWnSAiEA3AeCv4uEtJ554TwJPbNE3-v0xKTXJHeS3bGv6Vx6jiw")
    base_url = f"https://{os.getenv('ALIBABA_MAAS_HOST', 'ws-jo9nea7vxgzfwtxe.ap-southeast-1.maas.aliyuncs.com')}/compatible-mode/v1"
    
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url
    )
    
    # 包装客户端使其可调用
    callable_client = CallableClient(client)
    
    # 设置输出路径
    output_path = Path("./output/wanbi_guizhao.mp4")
    output_path.parent.mkdir(exist_ok=True)
    
    print(f"开始渲染《{EPISODE.title}》...")
    print(f"输出路径: {output_path}")
    print(f"预算: $14")
    
    try:
        result = await produce_authored_episode(
            EPISODE,
            output_path=output_path,
            llm=callable_client,
            budget_usd=14.0  # 设置预算限制
        )
        
        print(f"渲染完成！输出文件: {output_path}")
        print(f"最终成本: ${result.get('cost', 'unknown')}")
        print("渲染成功！")
        
    except Exception as e:
        print(f"渲染过程中出现错误: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main())