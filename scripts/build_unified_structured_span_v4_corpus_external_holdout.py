from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-04"
PARSER_PATH = ROOT / "src/domain/unified_jd_structured_spans_v4.py"
EXPECTED_PARSER_SHA256 = "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094"


JOBS: list[dict[str, str]] = [
    {
        "company": "字节跳动",
        "title": "东南亚品牌商城策略（经营分析）-TikTok Shop",
        "location": "上海",
        "employment_type": "正式",
        "job_function": "运营",
        "job_id": "A38340",
        "original_url": "https://jobs.bytedance.com/experienced/position/7676051557618043141/detail",
        "retrieved_at": "2026-09-04T11:04:45.478Z",
        "description": "1、针对品牌商家，结合平台经营目标，制定运营手段、资源投入、设计产品功能等帮助品牌生态得到正向发展，实现大盘业务整体增长，协同各国各协作部门完成上述策略落地；\n2、日常开展数据诊断分析，识别品牌商家供给和用户侧发展的问题和机会点，推动运营团队和XFN团队针对品牌的相关投入动作；\n3、洞察行业趋势与市场动态，结合平台特色，通过专项研究，与业务团队合作优化平台商家端权益和用户端权益的建设。",
        "requirements": "1、本科及以上学历，3年以上电商策略相关经验，兼具行业或商家运营经验优先；或电商相关战略或咨询背景；\n2、沟通协调能力强，能够调动和配合不同业务团队工作；\n3、具备数据分析能力，具备出色的信息收集及整合能力，独立分析指标、输出整体需求方案，并推动分步落地；\n4、英语无障碍沟通。",
    },
    {
        "company": "字节跳动",
        "title": "关卡策划（JRPG） - Bluesea Studio",
        "location": "北京",
        "employment_type": "正式",
        "job_function": "游戏策划",
        "job_id": "A135810",
        "original_url": "https://jobs.bytedance.com/experienced/position/7669706138068175109/detail",
        "retrieved_at": "2026-09-04T11:04:49.782Z",
        "description": "团队介绍：Bluesea工作室成立于2024年8月，当前涉足卡牌/RPG/SLG/竞技等多个品类，已经上线的游戏《放置少女》，各类新产品已蓄势待发。欢迎加入我们！\n1、负责游戏关卡相关设计，包括但不限于活动副本、场景交互解密探索、各类PVP竞技玩法等相关设计和制作工作；\n2、与战斗、文案、系统、数值等其他环节策划深入合作，优化关卡设计，调优关卡体验；\n3、与程序合作，研发、优化并维护关卡编辑器；\n4、与美术合作，积极跟进相关美术资产的落地工作。",
        "requirements": "1、对大世界、开放世界RPG、MMORPG游戏的关卡设计有深入的思考，熟悉市面上主流开放世界游戏和商业化成功的网游；\n2、对2D游戏的关卡设计有充分的认知，熟悉乐趣设计要点，有自己的方法论；\n3、有3年以上游戏关卡设计相关工作经验，有大世界、开放世界、精品2D内容向游戏的关卡设计和制作经验的优先；\n4、有优秀的关卡鉴赏、场景审美能力，对高品质关卡有自己的追求和理解；\n5、善于沟通，有良好的团队协作能力，责任心。",
    },
    {
        "company": "字节跳动",
        "title": "业务分析-CQC",
        "location": "北京",
        "employment_type": "正式",
        "job_function": "运营",
        "job_id": "A37068",
        "original_url": "https://jobs.bytedance.com/experienced/position/7668213188178151733/detail",
        "retrieved_at": "2026-09-04T11:04:53.541Z",
        "description": "1、承接业务交付指标与绩效指标的拆解落地，设计并推进配套考核机制与管理流程，确保核心指标有效承接与执行；\n2、基于业务指标表现开展系统性分析与下钻，识别交付与绩效管理中的关键问题，挖掘改进机会，输出可落地的解决方案，并对考核方案做治理和整合；\n3、围绕业务场景与管理诉求，构建数据观测与分析框架，打通管理指标与绩效考核的用数逻辑，沉淀分析范式并推动数据建设；\n4、协同数据分析、人力、技术等内外部团队，统筹推进复杂项目落地与推广。",
        "requirements": "1、本科及以上学历，专业不限，3~5年左右经营分析、数据分析、商业分析相关工作经验优先；\n2、学习能力强，逻辑思维清晰，有较强的数据敏感度，善于从数据中洞察业务动态和问题；\n3、具备较强的沟通能力、协调能力、推动能力，能够独立运作跨部门项目落地和交付；\n4、熟悉EXCEL、SQL等数据分析工具，有可视化分析工具经验者优先。",
    },
    {
        "company": "字节跳动",
        "title": "战略专家-TikTok Shop",
        "location": "上海",
        "employment_type": "正式",
        "job_function": "职能 / 支持 - 战略",
        "job_id": "A128075",
        "original_url": "https://jobs.bytedance.com/experienced/position/7667843545444813061/detail",
        "retrieved_at": "2026-09-04T11:04:56.517Z",
        "description": "1、重点支持国际电商业务，深度对接高速发展的国际团队，制定业务目标，输出分析报告，支持业务关键决策；\n2、根据各国电商行业现状与公司业务自身发展阶段，判断业务中长期战略方向，协助规划具体达成路径与目标，并能够跨团队协同目标制定，推动目标达成；\n3、搭建并完善电商行业各业务方向的核心指标体系，追踪并分析关键经营指标的变化趋势，挖掘经营机会，监控业务风险，协助业务决策判断；\n4、根据业务发展过程中的问题与痛点，基于内外部调研与数据挖掘进行专题分析，产出以深度定量分析为基础的策略建议，并推动解决方案落地（分析方向包括但不限于流量增长，用户表现，商品效率等）。",
        "requirements": "1、三年及以上战略咨询或互联网商业分析经验（电商相关优先），需要有良好的专业技能（包括但不限于市场研究，数据分析，项目推进等），并熟悉数据结构和相关工具的使用（Hive，SQL，Excel，Python等）；\n2、有结构化思考与分析能力，以及良好的商业敏感度，既能有全局判断，也能对具体问题深入下钻；\n3、英语听说读写流利能作为工作语言，会小语种为加分项，如日、韩、德、法等；\n4、有较强的沟通能力，能够跨部门，多团队协作，同时有解决问题的责任心，学习能力强，勤于思考，追求快速成长。",
    },
    {
        "company": "字节跳动",
        "title": "推荐算法工程师（直播） - TikTok Shop",
        "location": "北京、上海",
        "employment_type": "正式",
        "job_function": "研发",
        "job_id": "A153051A",
        "original_url": "https://jobs.bytedance.com/experienced/position/7667405882653935877/detail",
        "retrieved_at": "2026-09-04T11:05:00.702Z",
        "description": "团队介绍：TikTok Shop 是 TikTok 旗下的内容电商业务，致力于成为用户发现并获取优价好物的首选平台。面向直播电商、视频内容电商、货架电商等多元购物场景，国际电商持续为全球用户提供更个性化、更主动、更高效的消费体验，也为商家提供稳定、可靠、可持续增长的平台服务，推动“新奇好物畅销全球，美好生活触手可得”的使命落地。\n目前，国际电商算法团队分布在中国、美国、新加坡等多个国家和地区，深度参与全球化业务建设。加入我们，你将有机会面向全球用户、商家和商品生态，与跨区域的产品、工程、运营和业务团队协作，持续提升商品供给质量、用户购物体验、平台交易效率与履约体验，共同探索内容电商与智能购物的新模式。\nData-国际电商团队是 TikTok Shop 的核心算法技术力量，专注于电商场景下的算法创新与规模化落地，方向包括但不限于：生成式推荐与大规模 Foundation Model、多模态商品理解与内容生成、搜索与导购、智能客服、风控治理、物流履约优化、商家经营智能化，以及 Agentic 智能体在电商全链路中的应用。我们希望通过先进的算法能力，帮助用户更高效地发现感兴趣的商品，帮助商家实现更高质量的经营增长，并持续提升交易各环节的智能化水平。\n在这里，你将与一流的产品和技术团队合作，面对复杂且真实的国际化电商挑战，推动前沿技术在大规模业务场景中落地，与团队一起创造更多可能。\n1、参与千万~亿级规模的电商个性化推荐算法的优化，主要包括Feeds的电商直播推荐、新用户推荐、直播冷启动、长期价值建模、体验优化等工作；\n2、通过表征学习、深度学习、迁移学习、多任务学习等技术提升信息匹配的效率，让每个用户可以便捷的找到好的主播和优质的货品；\n3、挖掘和分析海量用户行为数据，进行用户长短期兴趣建模，以及潜在兴趣预测、探索，提升推荐的精准性和发现性；\n4、通过算法自动挖掘优质、专业、高口碑的商品和主播，构建良性的循环机制，优化内容电商生态；\n5、结合内容电商的业务特性，进行模型和算法创新，打造业界领先的推荐算法和系统。",
        "requirements": "1、扎实的算法和数据结构基础，优秀的编码能力；\n2、机器学习基础扎实，熟悉CF、MF、FM、word2vec、LR、GBDT、DNN、Wide&Deep等常用的算法模型；\n3、熟悉以下任何一个开源工具：XGBoost、TensorFlow、PyTorch；熟悉C++和Python语言，熟悉Linux开发环境；\n4、具备优秀的学习能力和良好的团队合作精神；\n5、有个性化推荐、广告、信息检索、自然语言处理、机器学习等相关领域研究或者项目实践经验的优先；\n6、在KDD、NeurIPS、WWW、SIGIR、WSDM、ICML、IJCAI、AAAI、RecSys等会议发表过论文，或者有过数据挖掘/机器学习相关的竞赛经历的优先。",
    },
    {
        "company": "字节跳动",
        "title": "算法工程师 - 今日头条",
        "location": "北京",
        "employment_type": "正式",
        "job_function": "研发 - 算法",
        "job_id": "A115691A",
        "original_url": "https://jobs.bytedance.com/experienced/position/7665255532760041781/detail",
        "retrieved_at": "2026-09-04T11:05:15.087Z",
        "description": "团队介绍：今日头条推荐算法团队，致力于为用户提供个性化新闻和信息推荐服务，提升头条产品的用户体验。我们的业务涉及内容的个性化分发、生态与质量治理、热点和垂类等多个方向。在这里，你可以研究和改进最前沿的深度学习算法、并在推荐系统中结合LLM等前沿技术探索新的边界，结合对产品、数据的深度分析，将技术应用到实际业务中，服务数亿用户。\n1、利用机器学习技术，改进悟空浏览器的推荐系统，优化数亿用户的阅读体验；\n2、参与召回、排序、混排等通用推荐算法创新与改进；\n3、和资深同事一起在业务中实践字节跳动推荐算法，探索业务与算法的新边界。",
        "requirements": "1、热爱计算机科学和互联网技术，对人工智能类产品有浓厚兴趣；\n2、具备扎实的机器学习基础，熟悉推荐算法、深度学习算法、统计学习方法等优先；\n3、具备较强的编码能力，熟悉Linux开发环境，熟悉C++和Python语言优先；\n4、优秀的分析问题和解决问题的能力，对解决具有挑战性问题充满激情。",
    },
    {
        "company": "字节跳动",
        "title": "搜索广告产品运营（本地推方向）-抖音生活服务",
        "location": "北京、上海",
        "employment_type": "正式",
        "job_function": "运营 - 产品运营",
        "job_id": "A10062A",
        "original_url": "https://jobs.bytedance.com/experienced/position/7664538023490275589/detail",
        "retrieved_at": "2026-09-04T11:05:18.086Z",
        "description": "1、负责字节跳动体系下抖音广告产品运营工作，针对产品阶段和营收目标制定有效的推进策略并能撬动各方资源协同，对产品的有效价值、客户和消耗覆盖负责；\n2、负责广告产品全生命周期管理，参与业界领先的抖音搜索广告业务运营，把握产品价值和主导发展趋势；\n3、负责搜索投放AI产品运营，制定和推进对客产品方案和GTM策略，与团队共同打造先进的AI智能投放系统；\n4、协同销售与业务运营，建立伙伴关系，提升产品影响力，助力实现搜索产品渗透提升和收入增长目标；\n5、清晰理解客户与产品需求，准确把握判断需求合理性及价值空间，并推动产品迭代优化。",
        "requirements": "1、3-5年产品运营经验，有广告产品运营背景，有AI类投放产品运营经验优先；\n2、对效果类产品各阶段推进策略有深刻理解，并具有较强的问题解决能力及学习能力；\n3、具备数据分析能力，擅长通过数据发现产品推进中的问题与机会点；\n4、有负责人意识，有执行力和推动力，善于整合资源，能够把制定的策略落实到位并获得业务结果；\n5、善于沟通，能和各合作方建立良好和牢固的合作关系，获取所需的支持和资源。",
    },
    {
        "company": "字节跳动",
        "title": "大模型技术服务专家 - 火山引擎",
        "location": "深圳",
        "employment_type": "正式",
        "job_function": "研发 - 运维",
        "job_id": "A182329A",
        "original_url": "https://jobs.bytedance.com/experienced/position/7663333383728597301/detail",
        "retrieved_at": "2026-09-04T11:05:21.655Z",
        "description": "团队介绍：火山引擎是字节跳动旗下云和AI服务平台，将字节跳动快速发展过程中积累的增长方法、技术能力和应用工具开放给外部企业，通过云和AI技术，推进企业智能化转型，激发增长潜能。\n1、面向客户大模型业务场景提供技术保障，深度排查并解决API调用异常、性能与稳定性等问题；\n2、面向客户分析模型生成效果问题，包括文本模型、多模态模型、生图/生视频模型等；从Prompt、上下文、参考素材、参数配置、工具调用、结构化输出等维度提供可执行的优化建议；\n3、支持复杂Agent场景，包括Agent编排、Skill/Tool调用、记忆管理、Agent Loop、Multi-Agent/A2A协作，以及异常重试、FaLLBack等机制设计与排查；\n4、联动产品、研发、算法、SRE等团队定位和解决问题；在客户业务受影响时，完成问题止损、进展同步、风险管理和复盘，推动问题高效闭环；沉淀排障手册、效果优化指南和最佳实践，提升团队支持效率；\n5、基于大模型落地业务，提炼高频问题和具备工具化价值的场景，结合前沿模型应用框架，构建可复用的业务Skill、Agent及自动化工具。",
        "requirements": "1、计算机、人工智能、软件工程、数字媒体等相关专业本科及以上学历；具备AI应用、模型服务、技术支持、解决方案或企业项目交付经验者优先；\n2、熟练掌握Python或Golang，具备代码调试、日志分析和问题定位能力；\n3、熟悉大模型应用，具备Prompt优化、上下文管理、工具调用、结构化输出、效果评测、复杂负面案例分析或业务落地等任一方向经验者优先；\n4、熟悉Agent工程化，具备以下方向经验者优先：\n1）LangChain、LangGraph、MCP、A2A等框架；\n2）Agent编排、工具调用、动态加载Skills/Tools；\n3）长短期记忆、上下文压缩、共享记忆；\n4）Loop Agent、Multi-Agent、异常重试、FaLLBack、降级和人工接管；\n5、了解模型服务性能与稳定性问题，能参与排查超时、限流、流式中断、并发抖动、生成失败等问题；了解TTFT、端到端时延、吞吐、错误率等指标者优先；有模型网关、监控告警、压测、云原生或分布式系统经验者优先；\n6、具备良好的客户意识、沟通表达和跨团队协作能力；能够清晰同步进展、控制风险并推动问题解决；对AI前沿技术、Agent和视频创作方向保持持续学习热情；有影视、短剧或其他内容生产行业经验者优先。",
    },
    {
        "company": "字节跳动",
        "title": "AI产品经理（Agent Friendly方向） - 飞书多维表格",
        "location": "北京",
        "employment_type": "正式",
        "job_function": "产品",
        "job_id": "A24249",
        "original_url": "https://jobs.bytedance.com/experienced/position/7663046602542074165/detail",
        "retrieved_at": "2026-09-04T11:05:26.162Z",
        "description": "团队介绍：多维表格是一款无代码搭建平台。凭借强大灵活的数据库、丰富富多样的视图组件、自由高效的自动化与工作流、开放的生态体系,以及专业级的BI仪表盘和应用模式,让每个人都能快速构建属于自己的业务系统。\n在此基础上,我们正在全面融合AI,让系统真正具备智能化能力。我们的愿景是：打造下一代办公人的Work OS--一个可以构建任何解决方案的平台，没有边界，没有限制。\n1、设计并推进飞书多维表格的Agent Friendly改造，定义高价值场景，输出改造方案并推动落地；\n2、与研发、跨团队深度协同，推动关键开放能力（API/MCP/CLI/Skill/SDK）的交付；\n3、以Agent和用户视角定义并提升多维表格开放能力的易用性、语义清晰度、可组合性与可扩展性；\n4、梳理业务域安全边界，明确高敏感数据和高风险操作的默认策略与兜底方案；\n5、持续跟踪Agent领域世界最新技术和实践，保持对前沿模型和工具的一手感受和认知。",
        "requirements": "1、本科及以上学历，对LLM与Agent技术有深入理解，熟悉Agent能力边界、产品架构、技术实现与评测方法，持续关注技术趋势；\n2、具备扎实的产品能力，对AI产品有热情，熟悉主流LLM与Agent产品；\n3、能从开发者视角判断API/工具的设计优劣，是Codex/Claude等AI Agent工具的深度用户，通晓架构和技术原理；\n4、良好的沟通协作、表达、逻辑思维、项目管理能力，善于跨团队合作；\n5、拥有高质量的个人作品集（开源项目、独立产品、AI工具、插件等）优先。",
    },
    {
        "company": "字节跳动",
        "title": "搜索内容质量评估（日语方向）-TikTok",
        "location": "北京",
        "employment_type": "正式",
        "job_function": "运营 - 编辑",
        "job_id": "A94289",
        "original_url": "https://jobs.bytedance.com/experienced/position/7662388144766044421/detail",
        "retrieved_at": "2026-09-04T11:05:31.859Z",
        "description": "1、识别评估规则中的空白、歧义、冲突及系统性偏差，推动形成清晰可执行的判断标准、规则补丁和落地口径，提升团队判断一致性；\n2、承接评估员升级的高复杂度、规则模糊、争议性案例，基于业务目标、规则口径和用户体验进行综合判断，输出高可信、可解释、可复盘的研判结论；\n3、将典型个案、争议场景和复杂判断经验沉淀为可复用的团队资产，包括Golden案例、FAQ、案例库、SOP补充说明等，支持一线高效执行；\n4、通过抽检、复盘、案例讲解等方式，帮助评估员提升复杂场景处理能力，降低重复升级、无效升级和误升级比例；\n5、对高风险场景、异常模式和潜在质量问题保持敏感，及时发现一线执行中的共性问题，推动形成长期治理方案，并将一线业务问题、规则痛点和工具缺口转化为产品研发需求，与产品、策略、工程、运营等团队协同，推动工具优化、流程改进和机制闭环。",
        "requirements": "1、本科及以上学历，英语、日语熟练读写和沟通，具备内容评估、搜索评估、内容审核、策略运营、风险控制、申诉处理、质量管理等内容研判运营工作经验，有复杂案例处理经验者优先；\n2、具备较强的深度研判能力，能够在信息冲突、规则不完整和场景不确定的情况下，抓住矛盾并做出高质量裁决；\n3、具备较强的标准抽象能力，能够将个人判断经验结构化，转化为团队可复用的标准规则、案例资产和执行口径；\n4、具备良好的全局风险识别能力，对高风险场景、系统性异常、规则漏洞和质量波动有较高敏感度；\n5、具备优秀的逻辑表达和跨团队协同能力，既能向评估员讲清楚判断标准，也能与产品、策略、工程等合作方高效沟通。\n加分项\n1、具备复杂内容审核、策略风控、复杂申诉处理等高难度研判经验，或曾担任资深质检负责人、规则专家，并实际参与过标准、规则或SOP制定；\n2、具备产品、策略、运营协同背景，能够将一线业务问题转化为可落地的产品需求、工具优化方案或机制改进建议。",
    },
    {
        "company": "字节跳动",
        "title": "云计算技术支持专家-火山引擎",
        "location": "深圳",
        "employment_type": "正式",
        "job_function": "研发 - 运维",
        "job_id": "913V",
        "original_url": "https://jobs.bytedance.com/experienced/position/7043769342991845640/detail",
        "retrieved_at": "2026-09-04T11:05:47.792Z",
        "description": "1、负责火山引擎公有云产品的售后服务支持，通过提供解决方案，指导用户合理使用云产品；\n2、通过电话、即时通讯、邮件等渠道的支持服务，主导客户复杂问题解决，保障客户服务体验与业务连续性；\n3、深度挖掘用户需求与产品痛点，提炼可落地的优化建议，推动产品研发团队迭代产品功能；\n4、持续提升售后服务质量，帮助团队提升服务能力，包括但不限于知识沉淀和培训赋能、推动服务流程和机制优化等。",
        "requirements": "1、计算机科学或者相关专业，5年以上传统/DevOps/开发/售后/技术服务工作经验；\n2、熟悉容器相关领域，对企业级Kubernetes 、容器网络、CSI存储插件等方向有深入了解；或者对机器学习平台及MLOps有深入了解，熟悉训练框架、训练编排等优先；\n3、有良好的沟通能力，较强的独立完成工作能力，做事认真、负责；\n4、了解使用各类调试、测试工具，具备Shell、Python、Golang、PyTorch、Java等开发能力者优先；\n5、良好的沟通能力，关注细节，主观能动性强，具有以客户为中心的理念，公有云技术支持经验优先。",
    },
    {
        "company": "字节跳动",
        "title": "网络运维工程师-稳定性方向",
        "location": "深圳",
        "employment_type": "正式",
        "job_function": "研发 - 运维",
        "job_id": "A150188",
        "original_url": "https://jobs.bytedance.com/experienced/position/7287527004738521381/detail",
        "retrieved_at": "2026-09-04T11:06:00.890Z",
        "description": "1、参与字节跳动全球骨干网络、数据中心网络建设和维护工作，并持续优化；\n2、负责超大规模网络集群监控平台、自动化平台设计，不断提升网络管控能力，提升故障处理效率；\n3、负责字节跳动网络容量、风险及预案梳理和管控，降低网络故障发生概率；\n4、设计和主导字节网络运维体系，通过流程优化、平台优化等思路不断提升网络稳定性和日常工作效率。",
        "requirements": "1、计算机、通信相关专业本科及以上学历；\n2、熟悉TCP/IP、BGP、Vxlan等协议，熟练使用各种主流的网络监控和运维系统，熟练使用Python、Shell、Java、PHP等其中一门编程语言进行开发工作；\n3、有自驱意识，具备良好的沟通和团队协作能力；\n4、具有较强的实际操作能力，具有分析、解决复杂问题的能力；\n5、有互联网公司大型网络建设、维护经验或者设备厂商经验优先考虑。",
    },
    {
        "company": "字节跳动",
        "title": "网络运营工程师",
        "location": "深圳",
        "employment_type": "正式",
        "job_function": "研发 - 运维",
        "job_id": "A124569",
        "original_url": "https://jobs.bytedance.com/experienced/position/7289268765697952055/detail",
        "retrieved_at": "2026-09-04T11:06:04.055Z",
        "description": "1、负责字节跳动基础网络运营平台的规划设计、推进落地和版本迭代；\n2、负责收集业务网络基础数据，并对数据进行分析审计，提升网络健康度；\n3、负责网络故障率、网络可用性、网络容量水位、网络成本等的分析，为网络运维和架构设计提供运营数据；\n4、不断提升线上网络稳定性，优化线下工程流程，提升网络运营效率。",
        "requirements": "1、有网络运维工作经验，互联网运维相关背景为佳；\n2、熟悉TCP/IP、BGP等网络协议，熟练使用Python、Shell、Java、PHP等其中一门编程语言进行运营开发工作；\n3、熟悉常用的数据分析方法，较强的数据敏感性，根据数据分析结果设计自动化运营的方案，推动问题得到解决；\n4、熟悉大规模数据中心的监控系统、网络告警平台等运营平台的搭建和优化流程；\n5、具备良好的系统分析能力，良好的抽象思维和逻辑思维能力，独立分析问题解决问题的能力。",
    },
    {
        "company": "字节跳动",
        "title": "DCN网络运维工程师-Data",
        "location": "深圳",
        "employment_type": "正式",
        "job_function": "研发 - 运维",
        "job_id": "A234610",
        "original_url": "https://jobs.bytedance.com/experienced/position/7583906471214860597/detail",
        "retrieved_at": "2026-09-04T11:06:07.505Z",
        "description": "1、负责字节跳动超大数据中心物理网络和AI网络运维和网络优化工作；\n2、负责超大规模网络集群监控平台、自动化平台设计，不断提升网络管控能力，提升故障处理效率；\n3、设计和主导字节跳动网络运维体系，通过流程优化、平台优化等思路不断提升网络稳定性和日常工作效率。",
        "requirements": "1、精通网络设计建设运维需要的知识：路由协议如OSPF/BGP、业务需求与容量规划，有实际的网络建设和运维经验；\n2、具有较强的实际操作能力，具有分析、解决复杂问题的能力；\n3、工作主动性强，具备良好的沟通协调能力，逻辑性强，善于团队合作。\n加分项\n1、熟练使用Python、Shell、Java、PHP等其中一门编程语言进行开发工作。",
    },
    {
        "company": "字节跳动",
        "title": "骨干网络运维工程师-Data",
        "location": "深圳",
        "employment_type": "正式",
        "job_function": "研发 - 运维",
        "job_id": "A100206A",
        "original_url": "https://jobs.bytedance.com/experienced/position/7583908774726682885/detail",
        "retrieved_at": "2026-09-04T11:06:10.729Z",
        "description": "1、负责字节跳动国内和海外物理网络骨干网、外网运维，包括故障处理、隐患修复等；\n2、负责字节跳动国内和海外外网质量优化；\n3、负责字节跳动骨干网架构优化；\n4、负责字节跳动运维体系建设，提升运维效率。",
        "requirements": "1、熟悉骨干网常用技术方案，拥有骨干网运维经验者优先；\n2、精通骨干网相关协议BGP、SR、MPLS等；\n3、自驱，具备良好的沟通协调能力，逻辑性强，善于团队合作。\n加分项\n1、熟练使用Python、Shell、Java、PHP等其中一门编程语言进行开发工作。",
    },
    {
        "company": "字节跳动",
        "title": "AIGC算法工程师-PICO",
        "location": "北京",
        "employment_type": "正式",
        "job_function": "研发 - 算法",
        "job_id": "A14418",
        "original_url": "https://jobs.bytedance.com/experienced/position/7585776219982186757/detail",
        "retrieved_at": "2026-09-04T11:06:24.696Z",
        "description": "1、参与AIGC与3D算法研发，并推动其在MR/XR应用中的落地；\n2、开发高效可扩展的生成算法管线，包括任务建模、数据集构建、模型训练与优化、推理加速及落地；\n3、跟踪3D视觉与图形学领域的最新研究进展，撰写论文及专利。",
        "requirements": "1、硕士及以上学位，计算机相关专业，3年以上算法相关工作经验；\n2、具备优秀的编程能力，熟练掌握Python/C/C++等计算机语言，熟悉常见深度学习框架；\n3、在AIGC/3D视觉领域具备扎实的算法基础，有AIGC相关项目经验；\n4、对视频/图像生成、多模态理解领域的最新进展有充分了解。\n加分项：\n1、具备以下任一领域研究经验者优先：\n1）视频生成：文/图生视频、长视频生成、高清视频生成、双目生成等；\n2）场景生成：全景图/视频生成、相机可控生成、世界模型等；\n3）新视角合成（3D/4D）：LVSM、Lyra等；\n2、在CVPR、ICCV、SIGGRAPH、NeurIPS等顶级会议或期刊发表论文者优先；\n3、ACM-ICPC、NOI/IOI、TopCoder等竞赛获奖者优先。",
    },
    {
        "company": "字节跳动",
        "title": "支付风控算法工程师-国际支付",
        "location": "北京",
        "employment_type": "正式",
        "job_function": "研发 - 算法",
        "job_id": "A60717",
        "original_url": "https://jobs.bytedance.com/experienced/position/7621097380970367237/detail",
        "retrieved_at": "2026-09-04T11:06:27.956Z",
        "description": "1、开发全球支付场景下的通用盗用风险模型；\n2、推动Seq、Graph、LLM在风控领域下的应用，完善风控特征体系与样本评估体系；\n3、利用深度学习算法能力，解决跨国家、跨地区的通用模型建设，实现全球视角下的模型开发；\n4、负责建模流程优化，提升模型开发和部署效率，降低模型维护成本；\n5、研究前沿机器学习算法在风控领域的实践和应用。",
        "requirements": "1、数学或计算机专业本科及以上学历，扎实的计算机算法基础，熟悉机器学习基本理论；\n2、熟练掌握Python/Java/Scala等建模语言，熟练使用SQL/Hive/Spark/Flink等数据统计工具；\n3、精通机器学习、多目标学习、深度学习、在线学习算法，具备良好的编码习惯和工程优化能力；\n4、3年以上数据挖掘或机器学习相关工作经历；\n5、具备自然语言处理、图谱挖掘、欺诈检测经验优先；有信贷、支付风控、搜推相关经验优先。",
    },
    {
        "company": "字节跳动",
        "title": "视频模型应用算法工程师/专家-Seed",
        "location": "北京",
        "employment_type": "正式",
        "job_function": "研发 - 算法",
        "job_id": "A85070",
        "original_url": "https://jobs.bytedance.com/experienced/position/7626308673237633285/detail",
        "retrieved_at": "2026-09-04T11:06:31.179Z",
        "description": "团队介绍：字节跳动 Seed 团队成立于 2023 年，致力于寻找通用智能的新方法，追求智能上限，为科技和社会发展作出贡献。\nSeed 团队在 AI 领域拥有长期愿景与决心，团队研究方向涵盖 MLLM、GenMedia、AI for Science、机器人等，在中国、新加坡、美国等地设有实验室和岗位。目前，团队已推出业界领先的通用大模型以及前沿的多模态能力，支持豆包、即梦、TRAE 等超过 50 个应用场景，并通过火山引擎开放给企业客户。第三方数据显示，豆包 App 用户量在中国市场排名第一，豆包大模型日均 Token 调用量行业领先。\n1、负责视频模型的应用技术研究和开发，面向豆包AI创作业务目标优化视频生成模型效果；\n2、构建训练所需的高质量数据链路、高效准确的自动化评估模型；\n3、业务数据分析及应用策略、创作Agent优化。",
        "requirements": "1、1-5年计算机视觉一个或多个领域的研究和实践经验，包括但不限于以下方向；\n1）图像视频的生成/编辑；\n2）多模态数据生产或多模态模型评测；\n3）多模态RL&RM算法；\n2、对AI技术的实际落地和突破性应用充满热情，业务意识优秀，擅长线上数据分析，对数据敏感；\n3、良好的自驱力，思维敏捷，追求本质，敢于挑战未知问题，乐于在技术攻关中探索技术前沿，能主动学习并快速成长；\n4、有产品落地经验、评测Benchmark构建经验者优先。",
    },
    {
        "company": "字节跳动",
        "title": "大模型评测算法工程师-AI数据与安全",
        "location": "北京",
        "employment_type": "正式",
        "job_function": "研发 - 算法",
        "job_id": "A229374A",
        "original_url": "https://jobs.bytedance.com/experienced/position/7626658537711896837/detail",
        "retrieved_at": "2026-09-04T11:06:34.162Z",
        "description": "1、主导大模型评测集构建与迭代，制定规范与质量校验标准，保障评测数据质量与针对性，支撑模型全面评估；\n2、设计算法与工具，实现评测结果自动化量化分析、缺陷定位及根因追溯，输出分析报告，为模型迭代提供数据支撑；\n3、探索大模型缺陷检测和红蓝对抗技术，设计对抗性评测方案，挖掘模型安全漏洞和能力边界，提升模型鲁棒性与安全性；\n4、跟踪前沿评测技术与Benchmark趋势，开展技术调研与创新实践，推动评测体系升级；\n5、参与评测工具算法设计与开发，优化评测效率与自动化水平，提升团队研发效能。",
        "requirements": "1、硕士学位及以上，计算机科学、人工智能、数学、统计学等相关专业；\n2、扎实掌握机器学习、深度学习核心理论，熟悉大模型底层原理，了解常见大模型的特性与评测方法；\n3、具备扎实的编程能力，熟悉PyTorch等深度学习框架，能独立完成算法实现与调试；\n4、具备良好的逻辑思维与问题解决能力，对大模型评测、缺陷检测、红蓝对抗等领域有强烈的探索欲，能快速跟进前沿技术并落地实践；\n5、具备良好的沟通协作能力与团队意识，能清晰表达技术思路，高效推进跨团队协作项目，具备一定的文档撰写能力。\n加分项\n1、有大模型评测集构建、自动化评测工具开发经验，熟悉主流评测Benchmark者优先；\n2、有大模型缺陷检测、红蓝对抗、安全对齐相关研究或项目经验者优先；\n3、熟悉多模态大模型评测技术，有图像、文本跨模态评测经验者优先；\n4、在顶会（如NeurIPS、ICML、ACL、EMNLP等）发表过大模型相关论文，或在算法竞赛中取得优异成绩者优先。",
    },
    {
        "company": "字节跳动",
        "title": "机器学习负责人（搜索算法）-TikTok内容生态 Machine Learning Leader (Search Algorithm) - TikTok Content Ecology",
        "location": "北京",
        "employment_type": "正式",
        "job_function": "研发 - 算法",
        "job_id": "A86945",
        "original_url": "https://jobs.bytedance.com/experienced/position/7649353067440605493/detail",
        "retrieved_at": "2026-09-04T11:06:37.167Z",
        "description": "1、团队领导与执行：领导并指导一个由约10名机器学习工程师组成的高效团队；全面负责团队的技术路线图（产品路径图）、执行力、生产力以及在组织内部的整体业务影响力；\n2、战略愿景：制定OKR并确立长期技术愿景，将其转化为TikTok搜索业务的业务增长；\n3、卓越技术：保持在AI/ML、CV/NLP、搜索/推荐和生成式AI（GenAI）领域的工业界和学术界前沿；确保团队在算法/建模以及大规模工程落地（生产环境实现）两方面均保持业界领先水平；\n4、跨职能协作：促进跨团队、跨职能的高效、高带宽合作，共同推进统一的AI战略项目。\n1.Team Leadership & Execution: Lead and mentor an efficient team of around 10 machine learning engineers; take full charge of the team's technical roadmap, execution capability, productivity and overall business influence within the organization;\n2.Strategic Vision: Set OKRs and define long-term technical vision, and translate them into business growth for TikTok Search;\n3.Technical Excellence: Stay at the forefront of industry and academia in AI/ML, CV/NLP, search/recommendation and Generative AI (GenAI); ensure the team maintains industry-leading capabilities in algorithm modeling and large-scale engineering deployment in production environments;\n4.Cross-functional Collaboration: Drive efficient and high-bandwidth cooperation across teams and functions to advance unified AI strategic projects.",
        "requirements": "1、本科及以上学历，计算机科学等相关专业，或具备同等的实际工作经验；5年以上软件工程实操经验，并专注于AI/ML、CV/NLP以及推荐/搜索算法；\n2、2年以上大模型/多模态大模型（LLM/MLLM）实操经验，特别是在后训练（Post-Training，如SFT、RLHF）和/或推理优化领域；1年以上Agentic Modeling、工作流及相关框架的开发经验；\n3、1年以上技术团队管理或领导经验（有团队管理经验者优先）；扎实掌握机器学习基础知识，并熟悉现代AI技术栈与基础设施；\n4、具备定义长期技术愿景并带领团队交付可衡量业务成果的成功案例；具备优秀的沟通与人际交往能力，能够与多元化的全球团队进行无缝协作。\n1.Bachelor's degree or above in Computer Science or related majors, or equivalent practical work experience; over 5 years of hands-on software engineering experience focusing on AI/ML, CV/NLP, recommendation and search algorithms;\n2.Over 2 years of practical experience with large language models and multimodal large models (LLM/MLLM), especially in Post-Training including SFT, RLHF and/or inference optimization; over 1 year of development experience in Agentic Modeling, workflows and related frameworks;\n3.Over 1 year of experience in managing or leading technical teams (team management experience is preferred); solid grasp of fundamental machine learning knowledge and familiarity with modern AI tech stack and infrastructure;\n4.Proven track record of defining long-term technical vision and leading teams to deliver measurable business outcomes; possess strong communication and interpersonal skills to collaborate seamlessly with diverse global teams.",
    },
]


def at(text: str, occurrence: int = 0) -> dict[str, Any]:
    return {"text": text, "occurrence": occurrence}


ANNOTATIONS: list[dict[str, Any]] = [
    {
        "job_id": "A38340",
        "category": "responsibility",
        "source_section": "description",
        "source_text": "洞察行业趋势与市场动态，结合平台特色，通过专项研究，与业务团队合作优化平台商家端权益和用户端权益的建设",
        "wrappers": [
            {"kind": "prefix", "marker": "洞察", "content": "行业趋势与市场动态"},
            {"kind": "prefix", "marker": "结合", "content": "平台特色"},
            {"kind": "prefix", "marker": "通过", "content": "专项研究"},
            {"kind": "prefix", "marker": "与业务团队合作优化", "content": "平台商家端权益和用户端权益的建设"},
        ],
        "connectors": [
            {**at("与", 0), "role": "surface"},
            {**at("和"), "role": "surface"},
        ],
        "coordinations": [
            {"role": "surface", "members": ["行业趋势", "市场动态"], "connectors": [at("与", 0)]},
            {"role": "surface", "members": ["平台商家端权益", "用户端权益"], "connectors": ["和"]},
        ],
        "shared_scopes": [
            {"kind": "result", "span": "的建设", "applies_to": ["平台商家端权益", "用户端权益"]},
        ],
        "example_attachments": [],
        "projection": {
            "surface_items": ["行业趋势", "市场动态", "平台特色", "专项研究", "平台商家端权益", "用户端权益"],
            "examples": [],
        },
    },
    {
        "job_id": "A135810",
        "category": "responsibility",
        "source_section": "description",
        "source_text": "负责游戏关卡相关设计，包括但不限于活动副本、场景交互解密探索、各类PVP竞技玩法等相关设计和制作工作",
        "wrappers": [
            {"kind": "prefix", "marker": "负责", "content": "游戏关卡相关设计"},
            {"kind": "prefix", "marker": "包括但不限于", "content": "活动副本、场景交互解密探索、各类PVP竞技玩法等相关设计和制作工作"},
        ],
        "connectors": [
            {**at("、", 0), "role": "example"},
            {**at("、", 1), "role": "example"},
            {**at("和"), "role": "surface"},
        ],
        "coordinations": [
            {
                "role": "example",
                "members": ["活动副本", "场景交互解密探索", "各类PVP竞技玩法"],
                "connectors": [at("、", 0), at("、", 1)],
            },
            {"role": "surface", "members": ["相关设计", "制作工作"], "connectors": ["和"]},
        ],
        "shared_scopes": [],
        "example_attachments": [
            {
                "cue": "等",
                "parent": "相关设计和制作工作",
                "examples": ["活动副本", "场景交互解密探索", "各类PVP竞技玩法"],
            },
        ],
        "projection": {
            "surface_items": ["游戏关卡相关设计", "相关设计", "制作工作"],
            "examples": ["活动副本", "场景交互解密探索", "各类PVP竞技玩法"],
        },
    },
    {
        "job_id": "A37068",
        "category": "responsibility",
        "source_section": "description",
        "source_text": "构建数据观测与分析框架，打通管理指标与绩效考核的用数逻辑，沉淀分析范式并推动数据建设",
        "wrappers": [
            {"kind": "prefix", "marker": "构建", "content": "数据观测与分析框架"},
            {"kind": "prefix", "marker": "打通", "content": "管理指标与绩效考核的用数逻辑"},
            {"kind": "prefix", "marker": "沉淀", "content": "分析范式"},
            {"kind": "prefix", "marker": "推动", "content": "数据建设"},
        ],
        "connectors": [
            {**at("与", 0), "role": "surface"},
            {**at("与", 1), "role": "surface"},
            {**at("并"), "role": "surface"},
        ],
        "coordinations": [
            {"role": "surface", "members": ["数据观测", "分析"], "connectors": [at("与", 0)]},
            {"role": "surface", "members": ["管理指标", "绩效考核"], "connectors": [at("与", 1)]},
            {"role": "surface", "members": ["分析范式", "数据建设"], "connectors": ["并"]},
        ],
        "shared_scopes": [
            {"kind": "head", "span": "框架", "applies_to": ["数据观测", "分析"]},
            {"kind": "result", "span": "的用数逻辑", "applies_to": ["管理指标", "绩效考核"]},
        ],
        "example_attachments": [],
        "projection": {
            "surface_items": ["数据观测", "分析", "管理指标", "绩效考核", "分析范式", "数据建设"],
            "examples": [],
        },
    },
    {
        "job_id": "A128075",
        "category": "responsibility",
        "source_section": "description",
        "source_text": "挖掘经营机会，监控业务风险，协助业务决策判断",
        "wrappers": [
            {"kind": "prefix", "marker": "挖掘", "content": "经营机会"},
            {"kind": "prefix", "marker": "监控", "content": "业务风险"},
            {"kind": "prefix", "marker": "协助", "content": "业务决策判断"},
        ],
        "connectors": [],
        "coordinations": [],
        "shared_scopes": [],
        "example_attachments": [],
        "projection": {"surface_items": ["经营机会", "业务风险", "业务决策判断"], "examples": []},
    },
    {
        "job_id": "A153051A",
        "category": "responsibility",
        "source_section": "description",
        "source_text": "参与千万~亿级规模的电商个性化推荐算法的优化，主要包括Feeds的电商直播推荐、新用户推荐、直播冷启动、长期价值建模、体验优化等工作",
        "wrappers": [
            {"kind": "prefix", "marker": "参与", "content": "千万~亿级规模的电商个性化推荐算法的优化"},
            {"kind": "prefix", "marker": "主要包括", "content": "Feeds的电商直播推荐、新用户推荐、直播冷启动、长期价值建模、体验优化等工作"},
        ],
        "connectors": [
            {**at("、", 0), "role": "example"},
            {**at("、", 1), "role": "example"},
            {**at("、", 2), "role": "example"},
            {**at("、", 3), "role": "example"},
        ],
        "coordinations": [
            {
                "role": "example",
                "members": ["Feeds的电商直播推荐", "新用户推荐", "直播冷启动", "长期价值建模", "体验优化"],
                "connectors": [at("、", 0), at("、", 1), at("、", 2), at("、", 3)],
            },
        ],
        "shared_scopes": [],
        "example_attachments": [
            {
                "cue": "等",
                "parent": "千万~亿级规模的电商个性化推荐算法的优化",
                "examples": ["Feeds的电商直播推荐", "新用户推荐", "直播冷启动", "长期价值建模", "体验优化"],
            },
        ],
        "projection": {
            "surface_items": ["千万~亿级规模的电商个性化推荐算法的优化"],
            "examples": ["Feeds的电商直播推荐", "新用户推荐", "直播冷启动", "长期价值建模", "体验优化"],
        },
    },
    {
        "job_id": "A115691A",
        "category": "skill",
        "source_section": "requirements",
        "source_text": "具备扎实的机器学习基础，熟悉推荐算法、深度学习算法、统计学习方法等优先",
        "wrappers": [
            {"kind": "prefix", "marker": "具备扎实的", "content": "机器学习基础"},
            {"kind": "prefix", "marker": "熟悉", "content": "推荐算法、深度学习算法、统计学习方法等"},
            {"kind": "suffix", "marker": "优先", "content": "推荐算法、深度学习算法、统计学习方法等"},
        ],
        "connectors": [
            {**at("、", 0), "role": "surface"},
            {**at("、", 1), "role": "surface"},
        ],
        "coordinations": [
            {
                "role": "surface",
                "members": ["推荐算法", "深度学习算法", "统计学习方法"],
                "connectors": [at("、", 0), at("、", 1)],
            },
        ],
        "shared_scopes": [],
        "example_attachments": [],
        "projection": {
            "surface_items": ["机器学习基础", "推荐算法", "深度学习算法", "统计学习方法"],
            "examples": [],
        },
    },
    {
        "job_id": "A10062A",
        "category": "skill",
        "source_section": "requirements",
        "source_text": "具备数据分析能力，擅长通过数据发现产品推进中的问题与机会点",
        "wrappers": [
            {"kind": "prefix", "marker": "具备", "content": "数据分析能力"},
            {"kind": "prefix", "marker": "擅长", "content": "通过数据发现产品推进中的问题与机会点"},
        ],
        "connectors": [{**at("与"), "role": "embedded"}],
        "coordinations": [
            {"role": "embedded", "members": ["问题", "机会点"], "connectors": ["与"]},
        ],
        "shared_scopes": [],
        "example_attachments": [],
        "projection": {
            "surface_items": ["数据分析能力", "通过数据发现产品推进中的问题与机会点"],
            "examples": [],
        },
    },
    {
        "job_id": "A182329A",
        "category": "skill",
        "source_section": "requirements",
        "source_text": "熟练掌握Python或Golang，具备代码调试、日志分析和问题定位能力",
        "wrappers": [
            {"kind": "prefix", "marker": "熟练掌握", "content": "Python或Golang"},
            {"kind": "prefix", "marker": "具备", "content": "代码调试、日志分析和问题定位能力"},
        ],
        "connectors": [
            {**at("或"), "role": "surface"},
            {**at("、"), "role": "surface"},
            {**at("和"), "role": "surface"},
        ],
        "coordinations": [
            {"role": "surface", "members": ["Python", "Golang"], "connectors": ["或"]},
            {"role": "surface", "members": ["代码调试", "日志分析", "问题定位"], "connectors": ["、", "和"]},
        ],
        "shared_scopes": [
            {"kind": "suffix", "span": "能力", "applies_to": ["代码调试", "日志分析", "问题定位"]},
        ],
        "example_attachments": [],
        "projection": {"surface_items": ["Python", "Golang", "代码调试", "日志分析", "问题定位"], "examples": []},
    },
    {
        "job_id": "A24249",
        "category": "skill",
        "source_section": "requirements",
        "source_text": "对LLM与Agent技术有深入理解，熟悉Agent能力边界、产品架构、技术实现与评测方法，持续关注技术趋势",
        "wrappers": [
            {"kind": "prefix", "marker": "对", "content": "LLM与Agent技术有深入理解"},
            {"kind": "suffix", "marker": "有深入理解", "content": "LLM与Agent技术"},
            {"kind": "prefix", "marker": "熟悉", "content": "Agent能力边界、产品架构、技术实现与评测方法"},
            {"kind": "prefix", "marker": "持续关注", "content": "技术趋势"},
        ],
        "connectors": [
            {**at("与", 0), "role": "surface"},
            {**at("、", 0), "role": "surface"},
            {**at("、", 1), "role": "surface"},
            {**at("与", 1), "role": "surface"},
        ],
        "coordinations": [
            {"role": "surface", "members": ["LLM", "Agent"], "connectors": [at("与", 0)]},
            {
                "role": "surface",
                "members": ["Agent能力边界", "产品架构", "技术实现", "评测方法"],
                "connectors": [at("、", 0), at("、", 1), at("与", 1)],
            },
        ],
        "shared_scopes": [
            {"kind": "evidence", "span": "技术有深入理解", "applies_to": ["LLM", "Agent"]},
        ],
        "example_attachments": [],
        "projection": {
            "surface_items": ["LLM", "Agent", "Agent能力边界", "产品架构", "技术实现", "评测方法", "技术趋势"],
            "examples": [],
        },
    },
    {
        "job_id": "A94289",
        "category": "skill",
        "source_section": "requirements",
        "source_text": "英语、日语熟练读写和沟通",
        "wrappers": [
            {"kind": "suffix", "marker": "熟练读写和沟通", "content": "英语、日语"},
        ],
        "connectors": [
            {**at("、"), "role": "surface"},
            {**at("和"), "role": "embedded"},
        ],
        "coordinations": [
            {"role": "surface", "members": ["英语", "日语"], "connectors": ["、"]},
            {"role": "embedded", "members": ["读写", "沟通"], "connectors": ["和"]},
        ],
        "shared_scopes": [
            {"kind": "evidence", "span": "熟练读写和沟通", "applies_to": ["英语", "日语"]},
        ],
        "example_attachments": [],
        "projection": {"surface_items": ["英语", "日语"], "examples": []},
    },
    {
        "job_id": "913V",
        "category": "experience",
        "source_section": "requirements",
        "source_text": "5年以上传统/DevOps/开发/售后/技术服务工作经验",
        "wrappers": [
            {"kind": "prefix", "marker": "5年以上", "content": "传统/DevOps/开发/售后/技术服务工作经验"},
        ],
        "connectors": [
            {**at("/", 0), "role": "surface"},
            {**at("/", 1), "role": "surface"},
            {**at("/", 2), "role": "surface"},
            {**at("/", 3), "role": "surface"},
        ],
        "coordinations": [
            {
                "role": "surface",
                "members": ["传统", "DevOps", "开发", "售后", "技术服务"],
                "connectors": [at("/", 0), at("/", 1), at("/", 2), at("/", 3)],
            },
        ],
        "shared_scopes": [
            {"kind": "evidence", "span": "工作经验", "applies_to": ["传统", "DevOps", "开发", "售后", "技术服务"]},
        ],
        "example_attachments": [],
        "projection": {"surface_items": ["传统", "DevOps", "开发", "售后", "技术服务", "工作经验"], "examples": []},
    },
    {
        "job_id": "A150188",
        "category": "capability",
        "source_section": "requirements",
        "source_text": "具有较强的实际操作能力，具有分析、解决复杂问题的能力",
        "wrappers": [
            {"kind": "prefix", "marker": "具有较强的", "content": "实际操作能力"},
            {"kind": "prefix", "marker": at("具有", 1), "content": "分析、解决复杂问题的能力"},
            {"kind": "suffix", "marker": "的能力", "content": "分析、解决复杂问题"},
        ],
        "connectors": [{**at("、"), "role": "surface"}],
        "coordinations": [
            {"role": "surface", "members": ["分析", "解决复杂问题"], "connectors": ["、"]},
        ],
        "shared_scopes": [{"kind": "suffix", "span": "的能力", "applies_to": ["分析", "解决复杂问题"]}],
        "example_attachments": [],
        "projection": {"surface_items": ["实际操作能力", "分析", "解决复杂问题"], "examples": []},
    },
    {
        "job_id": "A124569",
        "category": "experience",
        "source_section": "requirements",
        "source_text": "有网络运维工作经验，互联网运维相关背景为佳",
        "wrappers": [
            {"kind": "prefix", "marker": "有", "content": "网络运维工作经验"},
            {"kind": "suffix", "marker": "为佳", "content": "互联网运维相关背景"},
        ],
        "connectors": [],
        "coordinations": [],
        "shared_scopes": [],
        "example_attachments": [],
        "projection": {"surface_items": ["网络运维工作经验", "互联网运维相关背景"], "examples": []},
    },
    {
        "job_id": "A234610",
        "category": "experience",
        "source_section": "requirements",
        "source_text": "有实际的网络建设和运维经验",
        "wrappers": [
            {"kind": "prefix", "marker": "有实际的", "content": "网络建设和运维经验"},
        ],
        "connectors": [{**at("和"), "role": "surface"}],
        "coordinations": [
            {"role": "surface", "members": ["网络建设", "运维"], "connectors": ["和"]},
        ],
        "shared_scopes": [
            {"kind": "evidence", "span": "经验", "applies_to": ["网络建设", "运维"]},
        ],
        "example_attachments": [],
        "projection": {"surface_items": ["网络建设", "运维"], "examples": []},
    },
    {
        "job_id": "A100206A",
        "category": "experience",
        "source_section": "requirements",
        "source_text": "拥有骨干网运维经验者优先",
        "wrappers": [
            {"kind": "prefix", "marker": "拥有", "content": "骨干网运维经验"},
            {"kind": "suffix", "marker": "者优先", "content": "骨干网运维经验"},
        ],
        "connectors": [],
        "coordinations": [],
        "shared_scopes": [],
        "example_attachments": [],
        "projection": {"surface_items": ["骨干网运维经验"], "examples": []},
    },
    {
        "job_id": "A14418",
        "category": "capability",
        "source_section": "requirements",
        "source_text": "具备优秀的编程能力",
        "wrappers": [
            {"kind": "prefix", "marker": "具备优秀的", "content": "编程能力"},
        ],
        "connectors": [],
        "coordinations": [],
        "shared_scopes": [],
        "example_attachments": [],
        "projection": {"surface_items": ["编程能力"], "examples": []},
    },
    {
        "job_id": "A60717",
        "category": "capability",
        "source_section": "requirements",
        "source_text": "具备良好的编码习惯和工程优化能力",
        "wrappers": [
            {"kind": "prefix", "marker": "具备良好的", "content": "编码习惯和工程优化能力"},
        ],
        "connectors": [{**at("和"), "role": "surface"}],
        "coordinations": [
            {"role": "surface", "members": ["编码习惯", "工程优化能力"], "connectors": ["和"]},
        ],
        "shared_scopes": [],
        "example_attachments": [],
        "projection": {"surface_items": ["编码习惯", "工程优化能力"], "examples": []},
    },
    {
        "job_id": "A85070",
        "category": "experience",
        "source_section": "requirements",
        "source_text": "1-5年计算机视觉一个或多个领域的研究和实践经验，包括但不限于以下方向",
        "wrappers": [
            {"kind": "prefix", "marker": "1-5年", "content": "计算机视觉一个或多个领域的研究和实践经验"},
            {"kind": "suffix", "marker": "包括但不限于以下方向", "content": "计算机视觉一个或多个领域的研究和实践经验"},
        ],
        "connectors": [
            {**at("或"), "role": "quantifier"},
            {**at("和"), "role": "surface"},
        ],
        "coordinations": [
            {"role": "surface", "members": ["研究", "实践"], "connectors": ["和"]},
        ],
        "shared_scopes": [
            {"kind": "prefix", "span": "计算机视觉一个或多个领域的", "applies_to": ["研究", "实践"]},
            {"kind": "evidence", "span": "经验", "applies_to": ["研究", "实践"]},
        ],
        "example_attachments": [],
        "projection": {"surface_items": ["研究", "实践"], "examples": []},
    },
    {
        "job_id": "A229374A",
        "category": "capability",
        "source_section": "requirements",
        "source_text": "具备良好的逻辑思维与问题解决能力，对大模型评测、缺陷检测、红蓝对抗等领域有强烈的探索欲，能快速跟进前沿技术并落地实践",
        "wrappers": [
            {"kind": "prefix", "marker": "具备良好的", "content": "逻辑思维与问题解决能力"},
            {"kind": "prefix", "marker": "对", "content": "大模型评测、缺陷检测、红蓝对抗等领域有强烈的探索欲"},
            {"kind": "suffix", "marker": "有强烈的探索欲", "content": "大模型评测、缺陷检测、红蓝对抗等领域"},
            {"kind": "prefix", "marker": at("能", 1), "content": "快速跟进前沿技术并落地实践"},
        ],
        "connectors": [
            {**at("与"), "role": "surface"},
            {**at("、", 0), "role": "example"},
            {**at("、", 1), "role": "example"},
            {**at("并"), "role": "surface"},
        ],
        "coordinations": [
            {"role": "surface", "members": ["逻辑思维", "问题解决"], "connectors": ["与"]},
            {
                "role": "example",
                "members": ["大模型评测", "缺陷检测", "红蓝对抗"],
                "connectors": [at("、", 0), at("、", 1)],
            },
            {"role": "surface", "members": ["快速跟进前沿技术", "落地实践"], "connectors": ["并"]},
        ],
        "shared_scopes": [
            {"kind": "suffix", "span": "能力", "applies_to": ["逻辑思维", "问题解决"]},
        ],
        "example_attachments": [
            {"cue": "等", "parent": "领域", "examples": ["大模型评测", "缺陷检测", "红蓝对抗"]},
        ],
        "projection": {
            "surface_items": ["逻辑思维", "问题解决", "领域", "快速跟进前沿技术", "落地实践"],
            "examples": ["大模型评测", "缺陷检测", "红蓝对抗"],
        },
    },
    {
        "job_id": "A86945",
        "category": "capability",
        "source_section": "requirements",
        "source_text": "具备优秀的沟通与人际交往能力，能够与多元化的全球团队进行无缝协作",
        "wrappers": [
            {"kind": "prefix", "marker": "具备优秀的", "content": "沟通与人际交往能力"},
            {"kind": "prefix", "marker": "能够与", "content": "多元化的全球团队进行无缝协作"},
        ],
        "connectors": [{**at("与", 0), "role": "surface"}],
        "coordinations": [
            {"role": "surface", "members": ["沟通", "人际交往"], "connectors": [at("与", 0)]},
        ],
        "shared_scopes": [
            {"kind": "suffix", "span": "能力", "applies_to": ["沟通", "人际交往"]},
        ],
        "example_attachments": [],
        "projection": {"surface_items": ["沟通", "人际交往", "多元化的全球团队进行无缝协作"], "examples": []},
    },
]


CORPUS_PATH = ROOT / f"datasets/unified_jd_structured_span_v4_corpus_external_sources_v1_{DATE}.json"
SELECTION_PATH = ROOT / f"datasets/unified_jd_structured_span_v4_corpus_external_selection_v1_{DATE}.json"
LABELS_PATH = ROOT / f"datasets/unified_jd_structured_span_v4_corpus_external_labels_v1_{DATE}.json"
FREEZE_PATH = ROOT / f"datasets/unified_jd_structured_span_v4_corpus_external_label_freeze_v1_{DATE}.json"
AI_CAMPUS_SPLIT_PATH = ROOT / "datasets/unified_jd_eval_split_v1_2026_09_03.json"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_span(source: str, spec: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(spec, str):
        text = spec
        occurrence = 0
    else:
        text = spec["text"]
        occurrence = int(spec.get("occurrence", 0))
    cursor = 0
    start = -1
    for _ in range(occurrence + 1):
        start = source.find(text, cursor)
        if start < 0:
            raise AssertionError(f"span not found: {text!r} occurrence={occurrence} in {source!r}")
        cursor = start + 1
    span = {"text": text, "start": start, "end": start + len(text)}
    assert source[span["start"] : span["end"]] == text
    return span


def resolve_fixture(index: int, annotation: dict[str, Any]) -> dict[str, Any]:
    source = annotation["source_text"]
    fixture_id = f"structured-corpus-external-v1-{index:03d}"

    wrappers = [
        {
            "kind": wrapper["kind"],
            "marker_span": resolve_span(source, wrapper["marker"]),
            "content_span": resolve_span(source, wrapper["content"]),
        }
        for wrapper in annotation["wrappers"]
    ]
    connectors = [
        {"span": resolve_span(source, connector), "role": connector["role"]}
        for connector in annotation["connectors"]
    ]
    coordinations = [
        {
            "id": f"gold-coord-{coord_index}",
            "role": coordination["role"],
            "member_spans": [resolve_span(source, member) for member in coordination["members"]],
            "connector_spans": [resolve_span(source, connector) for connector in coordination["connectors"]],
        }
        for coord_index, coordination in enumerate(annotation["coordinations"], start=1)
    ]
    shared_scopes = [
        {
            "id": f"gold-scope-{scope_index}",
            "kind": scope["kind"],
            "span": resolve_span(source, scope["span"]),
            "applies_to_member_spans": [resolve_span(source, member) for member in scope["applies_to"]],
        }
        for scope_index, scope in enumerate(annotation["shared_scopes"], start=1)
    ]
    attachments = [
        {
            "id": f"gold-example-{attachment_index}",
            "cue_span": resolve_span(source, attachment["cue"]),
            "parent_span": resolve_span(source, attachment["parent"]),
            "example_spans": [resolve_span(source, example) for example in attachment["examples"]],
        }
        for attachment_index, attachment in enumerate(annotation["example_attachments"], start=1)
    ]

    projection = annotation["projection"]
    for item in projection["surface_items"] + projection["examples"]:
        resolve_span(source, item)

    return {
        "id": fixture_id,
        "job_id": annotation["job_id"],
        "category": annotation["category"],
        "source_section": annotation["source_section"],
        "source_text": source,
        "annotation_status": "human_reviewed_before_v4_prediction",
        "wrappers": wrappers,
        "connector_labels": connectors,
        "coordinations": coordinations,
        "shared_scopes": shared_scopes,
        "example_attachments": attachments,
        "projection": projection,
    }


def ai_campus_source_ids() -> tuple[set[str], set[str]]:
    split = json.loads(AI_CAMPUS_SPLIT_PATH.read_text(encoding="utf-8"))
    cases = split["dev"]["cases"] + split["sealed_blind"]["cases"]
    urls = {case["source_url"] for case in cases}
    position_ids = {
        part
        for url in urls
        for part in url.split("/")
        if part.isdigit() and len(part) >= 16
    }
    return urls, position_ids


def validate_annotations(fixtures: list[dict[str, Any]], jobs_by_id: dict[str, dict[str, Any]]) -> None:
    assert len(JOBS) == len(ANNOTATIONS) == len(fixtures) == 20
    assert len(jobs_by_id) == 20
    assert len({job["original_url"] for job in JOBS}) == 20
    assert len({fixture["job_id"] for fixture in fixtures}) == 20
    assert Counter(fixture["category"] for fixture in fixtures) == {
        "responsibility": 5,
        "skill": 5,
        "experience": 5,
        "capability": 5,
    }
    connector_roles = {
        connector["role"]
        for fixture in fixtures
        for connector in fixture["connector_labels"]
    }
    assert connector_roles == {"surface", "embedded", "example", "quantifier"}

    for fixture in fixtures:
        job = jobs_by_id[fixture["job_id"]]
        section = job[fixture["source_section"]]
        assert section.count(fixture["source_text"]) == 1
        source = fixture["source_text"]
        for container in (fixture["wrappers"], fixture["connector_labels"], fixture["coordinations"], fixture["shared_scopes"], fixture["example_attachments"]):
            for value in container:
                for nested in value.values():
                    spans = nested if isinstance(nested, list) else [nested]
                    for span in spans:
                        if isinstance(span, dict) and {"text", "start", "end"} <= set(span):
                            assert source[span["start"] : span["end"]] == span["text"]


def main() -> None:
    assert sha256_file(PARSER_PATH) == EXPECTED_PARSER_SHA256, "frozen v4 parser changed"
    jobs_by_id = {job["job_id"]: job for job in JOBS}
    fixtures = [resolve_fixture(index, annotation) for index, annotation in enumerate(ANNOTATIONS, start=1)]
    validate_annotations(fixtures, jobs_by_id)

    ai_urls, ai_position_ids = ai_campus_source_ids()
    external_urls = {job["original_url"] for job in JOBS}
    external_position_ids = {job["original_url"].split("/position/", 1)[1].split("/", 1)[0] for job in JOBS}
    assert not (external_urls & ai_urls)
    assert not (external_position_ids & ai_position_ids)

    corpus_jobs: list[dict[str, Any]] = []
    for job in JOBS:
        raw_content = f"职位描述\n{job['description']}\n职位要求\n{job['requirements']}"
        corpus_jobs.append(
            {
                **job,
                "source_name": "字节跳动招聘官网",
                "source_partition": "experienced",
                "recruitment_type": "社会招聘",
                "raw_content": raw_content,
                "raw_content_sha256": sha256_text(raw_content),
                "raw_content_length": len(raw_content),
            }
        )

    corpus = {
        "corpus_version": "unified-jd-structured-span-v4-corpus-external-sources-v1",
        "created_at": DATE,
        "status": "collected_full_text_before_v4_prediction",
        "collection_method": "Rendered public detail pages read with computer-use; only the complete 职位描述 and 职位要求 blocks were retained.",
        "source_scope": {
            "source_name": "字节跳动招聘官网",
            "source_partition": "experienced",
            "source_board_url": "https://jobs.bytedance.com/experienced/position",
            "company_count": 1,
            "job_count": 20,
            "unique_job_ids": 20,
            "full_description_and_requirements_required": True,
            "known_limit": "Single-employer external holdout; business units and job families vary, but employer/source diversity is not claimed.",
        },
        "ai_campus_isolation": {
            "comparison_path": str(AI_CAMPUS_SPLIT_PATH.relative_to(ROOT)).replace("\\", "/"),
            "comparison_sha256": sha256_file(AI_CAMPUS_SPLIT_PATH),
            "exact_source_url_overlap_count": 0,
            "position_id_overlap_count": 0,
            "recruitment_partition": "experienced, not campus",
        },
        "model_call_count": 0,
        "jobs": corpus_jobs,
    }
    write_json(CORPUS_PATH, corpus)

    selection_fixtures: list[dict[str, Any]] = []
    for fixture in fixtures:
        job = jobs_by_id[fixture["job_id"]]
        raw_content = f"职位描述\n{job['description']}\n职位要求\n{job['requirements']}"
        section_text = job[fixture["source_section"]]
        section_span = resolve_span(section_text, fixture["source_text"])
        raw_span = resolve_span(raw_content, fixture["source_text"])
        selection_fixtures.append(
            {
                "id": fixture["id"],
                "job_id": fixture["job_id"],
                "company": job["company"],
                "title": job["title"],
                "original_url": job["original_url"],
                "raw_content_sha256": sha256_text(raw_content),
                "category": fixture["category"],
                "source_section": fixture["source_section"],
                "source_text": fixture["source_text"],
                "clause_span_in_section": section_span,
                "clause_span_in_raw_content": raw_span,
            }
        )

    selection = {
        "selection_version": "unified-jd-structured-span-v4-corpus-external-selection-v1",
        "created_at": DATE,
        "status": "frozen_before_labels_and_v4_predictions",
        "corpus": {
            "path": str(CORPUS_PATH.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(CORPUS_PATH),
            "job_count": 20,
        },
        "parser_freeze": {
            "path": str(PARSER_PATH.relative_to(ROOT)).replace("\\", "/"),
            "sha256": EXPECTED_PARSER_SHA256,
            "parser_was_not_imported_or_run": True,
        },
        "selection_policy": "After collecting complete experienced-hire pages, manually select exactly one category-eligible clause per unique job, with five fixtures per category. Freeze the job and clause selection before materializing labels or running v4.",
        "scope": {
            "fixture_count": 20,
            "fixtures_per_category": 5,
            "unique_job_per_fixture": True,
            "single_use_holdout": True,
        },
        "fixtures": selection_fixtures,
    }
    write_json(SELECTION_PATH, selection)

    labels = {
        "labels_version": "unified-jd-structured-span-v4-corpus-external-labels-v1",
        "contract_version": "canonical-items-contract-v1",
        "created_at": DATE,
        "status": "human_reviewed_pre_prediction_frozen",
        "annotator": "Codex coding agent",
        "prediction_status_at_labeling": "v4_parser_not_run_on_selection",
        "model_call_count": 0,
        "selection": {
            "path": str(SELECTION_PATH.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(SELECTION_PATH),
        },
        "annotation_policy": {
            "surface_items": "Atomic, independently inspectable exact source spans; generic wrappers are excluded from projection.",
            "connector_roles": "Every annotated coordination connector is classified as surface, embedded, example, or quantifier before prediction.",
            "shared_scope": "Shared prefixes, suffixes, heads, evidence, and results are represented once with explicit member-span edges.",
            "examples": "Named illustrative instances attach to an explicit source parent; open lists that state direct alternatives remain surface items.",
            "prediction_independence": "Selection and labels were built without importing or executing the frozen v4 parser.",
        },
        "fixtures": fixtures,
    }
    write_json(LABELS_PATH, labels)

    freeze = {
        "freeze_version": "unified-jd-structured-span-v4-corpus-external-label-freeze-v1",
        "frozen_at": DATE,
        "status": "frozen_before_v4_prediction",
        "purpose": "Single-use corpus-external holdout for the frozen v4 structured-span parser.",
        "artifacts": {
            "corpus": {"path": str(CORPUS_PATH.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(CORPUS_PATH)},
            "selection": {"path": str(SELECTION_PATH.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(SELECTION_PATH)},
            "labels": {"path": str(LABELS_PATH.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(LABELS_PATH)},
            "parser": {"path": str(PARSER_PATH.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(PARSER_PATH)},
            "builder": {"path": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(Path(__file__).resolve())},
        },
        "freeze_checks": {
            "job_count": 20,
            "fixture_count": 20,
            "unique_job_id_count": 20,
            "category_counts": dict(sorted(Counter(fixture["category"] for fixture in fixtures).items())),
            "connector_roles_present": sorted({connector["role"] for fixture in fixtures for connector in fixture["connector_labels"]}),
            "exact_source_url_overlap_with_ai_campus": 0,
            "position_id_overlap_with_ai_campus": 0,
            "all_projection_items_source_anchored": True,
            "all_structural_spans_validated": True,
            "v4_parser_imported": False,
            "v4_parser_run_count": 0,
            "model_call_count": 0,
        },
        "next_allowed_action": "Run the frozen v4 parser exactly once on these 20 source_text values, write raw predictions and a layer-separated report, then apply the frozen gates.",
    }
    write_json(FREEZE_PATH, freeze)

    print(json.dumps({"corpus": str(CORPUS_PATH), "selection": str(SELECTION_PATH), "labels": str(LABELS_PATH), "freeze": str(FREEZE_PATH)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
