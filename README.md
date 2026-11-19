# 武汉接线台

武汉数命 SPU 城市 AI 接待员，支持武汉与社区问答、自然语言行程规划和修改、路线地图及 SAIG 参赛咨询。DeepSeek 判断意图，Python 校验行程、事实引用和修改范围。

[观看 2 分钟演示片](https://robert-wdy.github.io/saig/) · [原画质下载](https://github.com/Robert-WDY/saig/releases/tag/promo-v1) · [报名项目简介](docs/release/报名材料.md) · [发布验收](docs/release/发布验收.md)

## 本机运行

需要 Python 3.11。源码附带已构建的浏览器脚本；更新前端源码后运行 `npm ci` 和 `npm run build`。从官方素材包生成手册索引：

~~~sh
python -m pip install -r requirements.lock
python ingest.py
python serve.py
~~~

运行服务前设置 `DEEPSEEK_API_KEY`。个人 Windows 环境也支持系统凭据 SAIG/DeepSeek。本机入口是 http://127.0.0.1:18943/ 。`GET /health` 每分钟缓存一次模型目录和配置模型 ID 的检查，不发送付费生成请求。可用 `SAIG_MODEL` 指定服务商实际列出的模型。默认模型 deepseek-flash 是服务商别名。高德 Web 服务密钥可以通过 `SAIG_AMAP_KEY` 提供。命令行或历史测试的模型请求不经过 HTTP 试用额度。

## 手机与公网部署

同一可信 Wi-Fi 内，在 Windows 上运行 `.\start-phone.ps1 -Address 本机无线网IPv4`。把窗口打印的完整链接在手机微信中打开；程序绑定指定网卡及端口 18944，使用单独的会话库。手机需能直连开发机；若防火墙拦截，只对受信任的专用网络允许该端口。局域网 HTTP 仅用于本地设备验收。

公网服务器需配置域名的 DNS、开放 80/443，安装 Docker Compose。在主机环境或私有 .env 中设置 `SAIG_DOMAIN`、`DEEPSEEK_API_KEY`、`SAIG_INVITE`（至少 24 字符的随机邀请串）。执行：

~~~sh
docker compose up --build -d
~~~

Caddy 负责 HTTPS。评委使用 `https://域名/#invite=邀请串` 直达；页面读取片段后从地址栏移除，在同一标签页中继续使用。普通读者可以匿名看首页与地图，生成问答需要邀请。模型请求含重试在内，每轮最多 32 次；额度按真实上游请求原子扣除，默认每会话每天 400 次、全站每天 3000 次，按北京时间零点更新；后两项用 SAIG_SESSION_CAP、SAIG_DAY_CAP 配置。会话在最后成功写入约 24 小时后清除，旧库首次升级起有 24 小时过渡期。点击“新对话”删除服务端记录后清除本页。GitHub Pages 提供作品主页和演示；实际问答由以上 Python 服务处理。

## 调用

启动后在浏览器打开[武汉接线台](http://127.0.0.1:18943/)。提问通过 `/chat` 交给接待员。行程板支持逐日查看停留、转场与抵达时间，并在比较完成后将实际行程数据导出为 PNG 对比图。估算时间按约十分钟显示，精确时刻用于程序验收。首页为 AI 绘制的武汉城市插画，接待员是赛事素材包里的官方江豚虚拟形象：待机眨眼，查资料时摇头思考，回答时开口讲解。浏览器支持中文语音时会朗读简短回复，可在接待台随时关闭。首页四张卡片对应赛题四项功能，每条回答标注所属功能。

[武汉地图](http://127.0.0.1:18943/city) 可以直接浏览景点、大学和美食街。点击实景照片标记或从地点菜单选择，查看简介、停留建议和资料出处。选中多处后可创建一日游，也可以加入已有方案的指定日期。地点位于校园或街区的参考位置，入校须核对学校当期公告。底图打包在项目内，按[武汉市界](https://geo.datav.aliyun.com/areas_v3/bound/420100.json)裁切 OpenFreeMap 的 OpenMapTiles / OpenStreetMap 路网与水系。城区和远郊共用本地矢量细节。地标模型为 AI 创作的卡通示意，模型与号码均锚定在地理坐标上。武汉地图可直接切换方案和日期，查看按游览顺序连接的站点及其计划时段。地点照片的作者、许可与原图链接见地点详情及 `data/atlas.json`，WebP 为缩放压缩版本。

地图支持类别、区域、游览主题、名称或地址组合筛选。市文旅局 [A级景区名录](https://wlj.wuhan.gov.cn/bsfw_27/wlml/lyjq/) 72 条记录与现有目录去重，木兰文化生态旅游区以各子景区供选择。名录和地点快照于 2026-11-19 核对；待确认开放或缺可靠位置的地点仅供浏览。目录给出的停留时长是规划预算。路线缺少路网证据时，新景区按两地点间距离预留估算转场。首页问候和答复头像使用[赛事素材包](https://shuming-official-file.markyin.com/static/file/SAIGS01CompetitionMaterials.zip)中的官方虚拟形象。

行程板的「路线地图」会打开 `/routes`，在同一浏览器标签页接续已生成的方案和日期。接待台与行程编辑器共用仅覆盖武汉市域的 2.5D 导览地图。标记来自现有 WGS84 坐标和 `data/route_points.json`，连线表示游览顺序。支持滚轮和双指缩放、逐站播放、查看全程或展开大图。地图侧栏可从可规划地点目录添加站点，也可点地图上的附近地点添加，列表和地图标记可以移除游览站。点“应用并重排行程”会复算当前方案当前天的转场和抵达时间，并审核全程约束。未通过会保留原行程；编辑试排只更新试排。可打开地点搜索，或为有坐标的步行和打车段打开分段导航。Leaflet 的 BSD-2-Clause 许可随本地静态资源附带。

~~~powershell
python app.py tool '汉口站' --tool location
python app.py tool '吃早点，再看老建筑，适合慢逛半天' --tool guide
python app.py rag '武汉的社区布局在哪两处？' --tool community
python app.py chat '住江汉路，想看老建筑。上午九点出发，下午一点结束，智民里必须保留。' --session visitor-1
python app.py chat '改成十点才出发，其余照旧。' --session visitor-1
~~~

GET /health 返回工具清单及索引大小。POST /tool 和 /rag 接受 JSON 对象，包含 tool 和 query。POST /chat 接受 query、可选 session 和 request_id；新对话可省略 session，客户端保存返回的会话标识并在后续追问时带上。重试同一个请求时复用 request_id。并发编辑同一会话遇到版本冲突会得到 409，调用方应读取最新回复后再决定是否重试。

工具包括城市知识 wuhan、社区 community、概念 spu、赛事 saig、位置 location、景点 attraction、美食 food 和攻略 guide。/tool 返回材料，/rag 对检索材料作带来源回答；location 直接走 /tool。

## 多项交付

多份行程或成果比较仍通过 `POST /chat` 提交。返回的 `deliverables` 按用户请求顺序列出各项成果，每项包含标识、类型、适用约束、依赖编号、状态和答复。通过审核的行程带独立的 `cards` 和 `option_id`，比较项的 `metrics` 按来源编号索引。客户端可分别展示通过、失败、资料不足和因依赖未完成而阻塞的成果。游客在同一会话选定备选后，正式行程出现在 `days`。

## 资料与更新

- 运行 python ingest.py --zip <文件路径> 可重新导入官方材料。省略参数时使用临时目录里的素材包，缺少时下载。data/handbooks.jsonl 保存中文旅游手册、武汉概览和两份 SPU 说明的可检索片段。PDF 定位使用从 1 起算的文件页码。攻略覆盖手册第 172–209 页，含主题游线、地铁串游和地铁站点参考。按页拆分的片段数不能等同独立路线数。[赛事素材 ZIP](https://shuming-official-file.markyin.com/static/file/SAIGS01CompetitionMaterials.zip)
- data/official.json 保存经核对的简明条目及日期。旧赛事说明与现行网页的截止时间有差异，活动规则只从带日期的官网快照回答。新公告发布后需要复核并更新对应条目，再重启服务。武汉概览中的历史统计应按原资料年份使用。[赛事官网](https://www.dlife.love/saig/) · [武汉商务慢游攻略](https://sw.wuhan.gov.cn/xwdt/gzdt/202610/t20261008_2857351.shtml)
- python geodata.py 可刷新有公开点位的地点。其余目录地点返回片区、来源编号及地图搜索入口。街区中心与真实入口不同。景点、美食、攻略的资料覆盖面大于能逐站排程的地点目录。

## 行为边界

### 旅游规划

接待员可按半日、一日、二日、三日选择带出处的分日攻略。行程卡保存原版当天站序、实际采用的站点和增删差异。跨日审核记录重复游览、跨区转场、自由时间和明确给出的住宿衔接。人物、人数、交通要求、预算和用户报价按适用日期保存；当日变更仍经同一排程器复核。

data/road_network.json 保存 OpenStreetMap 地图参考点和有方向的 OSRM 步行/驾车路网。步行上限按集合点之间的路线审核；园内步行、无障碍设施和实时等待需另核。交通参考使用普通四乘客座出租车，计价器估价包含不确定性；只有可核实的费用上限或游客给出的适用固定报价才能用来通过硬预算。地铁线路图与手册接驳可离线使用。有 SAIG_AMAP_KEY 且提供具体日期时，程序也查询高德日期和出发时刻对应的公交方案。数据来源及采集时间保存在路网文件，OSM 数据遵循 ODbL。独立更新已有坐标的路网可执行 python refresh_transport.py --routes-only。

运行 python -m unittest discover -v 验证程序规则。实际模型通过 python audit_trip_planning.py --base http://127.0.0.1:18943 --out <新目录> 检查游客请求、原卡、交通明细和修改后的状态。

1. 模型选择用户意图、工具和目标日。修改时另做字段定位，按用户原话提取改动并独立进行语义复核。固定字段类型和候选地点由程序验证。语义判断没有关键词路由。
2. 新计划优先混合检索攻略，模型从有出处的候选中选择。索引由 BM25、中文词片的 TF-IDF 降维稠密向量（LSA）及倒数排名融合组成。该版本无需远程 embedding 服务。回答附逐条原文、来源和定位；模型复核语义支持，程序检查引文引用是否存在。
3. 规划和交付共用 evaluate。它审核起止、时间预算、目的地、进站余量、必去/排除、访问窗口、片区和最多站数。耗时优先采用有证据的站间交通；缺资料时采用分区预算；这些通过结果只证明在预算假设下可行。游客要求精确实时到达、当日开放、无障碍全程、过敏保证或硬预算超出数据覆盖时，需要进一步核实。
4. 改线先按原句绑定日期、地点角色、时间字段和生效范围，再修改被授权的日期。游客委托接待员选替换站时，候选站要有支持所求活动的原文；程序按同一套约束排程，并在保留其他站和替换位置的前提下比较转场时间。无解时带审核失败原因尝试替代攻略。未确认取舍时保留原卡。preview 放入单独的临时结果。
5. SQLite 保存会话、原卡、人物关系和近期对话。人物关系带主语、关系、对象和原句。读回时从当前会话按人物、日期或站点选择对应记录，由程序渲染已保存的值。公开资料问答按子问题选工具、核对引文，多问可用到同一资料库的不同来源。当前请求整体提交；失败时保留已确认行程，重复请求按请求编号去重。

## 评测入口

运行 `python -m unittest discover -v`。覆盖基础规划、锁定日期、deliverables 依赖和版本校验、访客意图、知识引文、HTTP、配额及持久化。在线回归的入口为 `run_audit.py`，专题评测为 `audit_*.py` 及 `audit/`；按各脚本的 `--help` 选择。

真实浏览器脚本位于 `audit/check-frontend.cjs`。使用 Node 22+ 与 Chrome，以独立临时用户目录启动 Chrome 并传入 `--remote-debugging-port=0`，运行 `node audit/check-frontend.cjs <该用户目录> <证据输出目录>`。默认访问本机服务；SAIG_TEST_URL 可指定完整邀请地址，SAIG_LEGACY=1 可测试旧式确认框回退。会实际调用模型，测试证据目录不能复用作正式部署数据。

`GET /route-points` 提供 WGS84 参考点；`POST /chat` 提问；`POST /session/delete` 删除本次会话；`/rag` 和 `/tool` 用于本机开发。更多验收边界见 [项目规格](docs/SAIG城市AI接待员验收规格.md) 与 [当轮核对](docs/release/发布验收.md)。
