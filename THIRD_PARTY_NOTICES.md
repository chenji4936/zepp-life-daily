# 第三方参考与许可

本工具是非官方实验项目，与 Zepp Health、华米、小米和微信无隶属或背书关系。

## API 协议参考

1. [weihuiyong-coder/Zepp-Life-Steps](https://github.com/weihuiyong-coder/Zepp-Life-Steps)，参考提交 `8cb31912a7558a8fb91fbd2742be8bba2ad8bceb`，`server/python/vendor/zepp_login.py`、`lib/step-client.js` 以及该项目说明。
2. [miloce/Zepp-Life-Steps](https://github.com/miloce/Zepp-Life-Steps)，公开的 `zepp登录接口.py`；上述整合版说明引用提交 `1a6c24044a2aced028ac811c3eda8f00f465746c`。
3. [LiuJun-tao/Zepp-Life-Steps](https://github.com/LiuJun-tao/Zepp-Life-Steps)，参考提交 `f1e1910734614b316268ae31e8da5d22345ab72e`，`pages/api/ZeppLifeSteps.js` 中的数据上报协议。

`zepp_client.py` 根据这些公开实现的请求格式重新组织，加入固定认证端点、受限官方数据域名解析、关闭跳转与自动重试、脱敏错误处理、步数范围上传与二次确认。本项目不包含上述仓库的大段固定运动/心率/睡眠模板。**修复版使用步数汇总与自行生成的计步明细，并从同一数据区回读。2026-09-27 的一次独立真实账号测试获得用户微信端确认；不继承其他项目声称的兼容性或成功率，也不据此保证所有账号可用。**

补充技术资料（用于理解格式；未复制其中的整套实现）：

- [1](https://github.com/micw/hacking-mifit-api/blob/master/README.md)：当日汇总 GET 查询及 Base64 summary 解码。
- [1](https://xdaforums.com/t/xiaomi-mi-band-data-extraction-analytics-and-google-fit-sync-tools.3019156/page-5)：每分钟三字节的 category / intensity / steps 格式。本项目的合成样本独立生成，不含参考帖中的用户数据。

参考的整合仓库 LICENSE 在所查版本内容如下，保留其许可声明：

```text
MIT License

Copyright (c) 2025 Miloce

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 运行依赖

- Requests（支持 >=2.32.5,<3）：Apache License 2.0。兼容的已安装版本会直接复用；需要安装时先征求同意。不将第三方依赖源码捆绑在下载包内。
- Requests 可能安装 urllib3、certifi、charset-normalizer、idna 等依赖，其许可随各自发行包提供。
- 浏览器界面不加载外部字体、脚本、图片、统计分析或 CDN。

浏览器自动化测试可选依赖 Playwright，不是运行本工具所必需的依赖，也不包含在交付包中。
