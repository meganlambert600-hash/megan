# 🧋 奶茶省钱雷达 V3.0

面向郑州、外卖优先的公开优惠情报网页。部署在 GitHub Pages，GitHub Actions 每天北京时间 **09:37、17:00** 尝试采集公开资讯中的优惠线索。

> 重要：此版本不会登录美团、淘宝闪购、京东外卖或抖音，也没有获得这些平台的实时券库。自动发现的是公开 RSS 资讯中的**待核实线索**，不等于可领取优惠券。某天可能没有任何线索，这是正常结果。页面明确区分线索与手动收藏的真实优惠。不要将它用于抢券或自动下单。

## 页面功能

- 郑州优先、全国补充；重点品牌和关键词筛选。
- 云端公开资讯线索、来源状态与采集时间。
- 公开搜索辅助入口（外部搜索）、四个平台主页快捷入口。
- 自己手动添加优惠链接、标记已读、导出本地备份。
- 在用户本人正常登录并完成验证码后，批量导入页面可见文字、TXT、CSV、JSON 或活动截图；在浏览器本地识别品牌、优惠金额、期限和郑州适用范围，预览确认后保存为待核验记录。
- 响应式手机/电脑网页。

## 部署到现有 GitHub Pages

仓库地址：`https://github.com/meganlambert600-hash/megan`

1. 下载项目 ZIP 并解压。
2. 将 **`milk-tea-radar-v3` 文件夹内部**的内容上传到 GitHub 仓库的根目录（不是整个外层文件夹）：
   - `index.html`
   - `sources.json`
   - `data/offers.json`
   - `scripts/collect.py`
   - `.github/workflows/collect.yml`
   - `README.md`
3. 确认 GitHub Pages 仍然选择 `main` 分支、`/(root)`。
4. 打开仓库的 **Actions** → `Collect public coupon leads` → `Run workflow`，手动启动第一次采集。
5. 等待任务结束并刷新网站：`https://meganlambert600-hash.github.io/megan/`。

网页“刷新已发布数据”按钮只是获取仓库最新 JSON，**不会**直接启动 GitHub Actions。若想立即采集，使用第 4 步的 GitHub Actions 手动运行按钮。

## 采集规则

- 所有来源在 `sources.json` 中明确列出。采集器支持公开 RSS/Atom、合规公开 HTML 活动页及 Bing 公开搜索结果适配器；需要登录、App、小程序、验证码或私域权限的来源只记录诊断并跳过。
- 授权导入助手不读取账号密码、Cookie、会话或后台接口。截图 OCR 由浏览器本地执行，首次使用会下载开源 Tesseract.js 中文模型；请先裁掉手机号、地址、订单号等个人信息。
- 只保留含优惠词、且涉及奶茶饮品或外卖的资讯；最多 21 天内的新闻，单源最多 20 条。
- 标题、摘要和原始链接保留，状态始终为 `unverified`，不自动推断优惠金额与有效期。
- 按品牌、活动标题、券面额和日期线索生成指纹去重，保留首次/最近发现时间与多来源记录。来源失败或被合规跳过会展示明确状态，未抓到结果不填假数据。
- 有效来源与字段覆盖须经过实测后才可扩充。不要在源配置中填入需要登录或无授权的受限接口。

## 权限和安全

- GitHub Actions 需要 `contents: write` 才能将 `data/offers.json` 更新回仓库。若首次运行报 `403`，检查 **Settings → Actions → General → Workflow permissions**，选择允许工作流写入的仓库权限。
- 这个仓库是公开网站。绝不要把账号 Cookie、手机号、优惠券个人口令、Access Token 或密码写进 `sources.json`、工作流或公开 JSON。
- 定时任务可能延迟；长期不活跃的公开仓库可能被 GitHub 自动禁用计划任务。要定期检查 Actions 页面。
- 使用 GitHub Pages 和 Actions 本身不需要付费 API，但外部 RSS 源可能不可用、限流或改变格式，故不保证每天出现线索。

## 本地检查

```bash
python3 -m unittest discover -s tests -v
python3 scripts/collect.py
python3 -m http.server 8000
```

访问 `http://localhost:8000`。本地采集失败也会写入状态文件，网页仍可使用收藏和搜索功能。

## 后续数据源实测

采集器是可扩展的起点，不应被视为完成四平台实时优惠监测。下一步应测试平台官方公开活动、经授权的合作渠道、品牌公告等源是否能稳定返回金额、有效期、城市和原始领券入口，并为验证通过的来源编写独立适配器。
