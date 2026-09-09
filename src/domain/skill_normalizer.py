from __future__ import annotations

import copy
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Literal

SKILL_ONTOLOGY_VERSION = "skill-ontology-v5"

SkillQualifier = Literal[
    "project_experience",
    "internship_experience",
    "research_experience",
    "development_experience",
    "practical_experience",
    "open_source_experience",
]

# These are deliberately canonical, user-matchable labels. Fine-grained terms
# such as MCP, ReAct, and KV Cache remain traceability mentions unless the JD
# explicitly treats them as a standalone required skill.
SKILL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Agent Harness", r"Agent[\s-]*Harness"),
    ("Agent Runtime", r"Agent\s+Runtime"),
    (
        "Agent评测",
        r"(?:Agent|智能体)\s*(?:的\s*)?(?:Evaluation|评测|评估)",
    ),
    ("Agent系统研发", r"Agent\s*系统研发"),
    ("Agent Loop", r"Agent\s*Loop"),
    (
        "Agent项目",
        r"(?:完整的?\s*)?Agent(?:\s*(?:应用|系统)?|[^。；\n]{0,20})项目",
    ),
    ("Agent系统上线", r"(?:真实)?上线运行的?\s*(?:AI\s*)?Agent\s*系统"),
    ("机器人Agent", r"机器人\s*Agent"),
    ("工具调用Agent", r"工具调用\s*Agent"),
    (
        "Coding Agent",
        r"Coding(?=\s*/\s*Search\s*/\s*Productivity\s*Agent)|Coding\s*Agent",
    ),
    (
        "Search Agent",
        r"Search(?=\s*/\s*Productivity\s*Agent)|Search\s*Agent",
    ),
    ("Productivity Agent", r"Productivity\s*Agent"),
    ("生产级Agent平台", r"生产级\s*Agent\s*平台"),
    ("完整具身Agent项目", r"完整具身\s*Agent\s*项目"),
    ("具身Agent", r"具身\s*Agent"),
    ("LLM Agent", r"(?<![A-Za-z])LLM\s+Agent(?![A-Za-z])"),
    ("Agent Workflow", r"Agent\s+Workflow"),
    ("Agentic RL", r"Agentic\s+RL"),
    ("多智能体系统", r"多智能体系统"),
    ("大模型应用", r"大模型应用(?:开发)?"),
    ("复杂软件系统", r"复杂软件系统"),
    ("知识检索", r"知识检索"),
    ("文档理解", r"文档理解"),
    ("长期记忆", r"长期记忆"),
    ("任务调度", r"任务调度"),
    ("日志监控", r"日志监控"),
    ("数据平台", r"(?<!模型训练)数据平台"),
    ("MLOps", r"(?<![A-Za-z])MLOps(?![A-Za-z])"),
    ("自动化测试", r"自动化测试"),
    ("Python", r"(?<![A-Za-z])Python(?![A-Za-z])"),
    ("Java", r"(?<![A-Za-z])Java(?![A-Za-z])"),
    ("Go", r"(?<![A-Za-z])(?:Go|Golang)(?![A-Za-z])"),
    ("C++", r"C\+\+"),
    ("C#", r"C#"),
    ("Rust", r"(?<![A-Za-z])Rust(?![A-Za-z])"),
    ("JavaScript", r"JavaScript|(?<![A-Za-z.])JS(?![A-Za-z])"),
    ("TypeScript", r"TypeScript|(?<![A-Za-z])TS(?![A-Za-z])"),
    ("HTTP", r"(?<![A-Za-z])HTTP(?:\s*协议)?(?![A-Za-z])"),
    # ReAct is an Agent reasoning pattern, not the React frontend framework.
    # The outer extraction is case-insensitive, so opt this token back into
    # exact-case matching.
    ("React", r"(?<![A-Za-z])(?-i:React)(?![A-Za-z])"),
    ("Node.js", r"(?<![A-Za-z])Node(?:\.js|JS)(?![A-Za-z])"),
    ("编程语言", r"(?:主流)?编程语言"),
    ("操作系统", r"操作系统"),
    ("计算机网络", r"计算机网络"),
    ("向量数据库", r"向量数据库"),
    ("数据库", r"数据库"),
    ("SQL", r"(?<![A-Za-z])SQL(?![A-Za-z])"),
    ("SQL生成", r"SQL\s*生成"),
    ("PyTorch", r"PyTorch"),
    ("TensorFlow", r"TensorFlow"),
    ("PaddlePaddle", r"PaddlePaddle"),
    ("JAX", r"(?<![A-Za-z])JAX(?![A-Za-z])"),
    ("Agent框架", r"Agents?\s*(?:开发)?框架|智能体\s*(?:开发)?框架"),
    ("LangChain", r"LangChain"),
    ("LangGraph", r"LangGraph"),
    ("AutoGen", r"AutoGen"),
    ("LlamaIndex", r"LlamaIndex"),
    ("Web框架", r"Web\s*框架"),
    ("FastAPI", r"FastAPI"),
    ("Flask", r"(?<![A-Za-z])Flask(?![A-Za-z])"),
    ("Django", r"Django"),
    ("低代码平台", r"低代码平台"),
    ("Coze", r"(?<![A-Za-z])Coze(?![A-Za-z])"),
    ("Dify", r"(?<![A-Za-z])Dify(?![A-Za-z])"),
    ("OpenAI Agents SDK", r"OpenAI\s+Agents?\s+SDK"),
    ("OpenClaw", r"OpenClaw"),
    ("Hermes", r"(?<![A-Za-z])Hermes(?![A-Za-z])"),
    ("Pi", r"(?<![A-Za-z])Pi(?![A-Za-z])"),
    ("RAG", r"(?<![A-Za-z])RAG(?![A-Za-z])"),
    ("LLM API", r"(?:LLM|大模型)\s*的?\s*API(?:\s*调用|使用)?"),
    ("大模型训练", r"大模型\s*训练"),
    ("大模型后训练", r"(?:大模型\s*)?后训练"),
    ("后训练技术", r"后训练[^。；\n]{0,80}(?:相关)?技术"),
    ("大模型部署", r"大模型(?:量产)?部署"),
    (
        "大模型结构研发",
        r"(?:NN\s*)?大模型结构[^。；\n]{0,16}(?:研发|开发)",
    ),
    ("多模态模型", r"多模态(?:大)?模型"),
    ("Prompt Engineering", r"Prompt(?:\s*Engineering)?|提示词?(?:工程|设计)"),
    ("Context Engineering", r"Context\s*Engineering|上下文(?:管理|优化)"),
    (
        "Learning-based Planning",
        r"(?<![A-Za-z])Learning[\s-]+based\s+Planning(?![A-Za-z])",
    ),
    ("Task Planning", r"(?<![A-Za-z])Task\s+Planning(?![A-Za-z])"),
    ("Memory Retrieval", r"(?<![A-Za-z])Memory\s+Retrieval(?![A-Za-z])"),
    ("Skill Selection", r"(?<![A-Za-z])Skill\s+Selection(?![A-Za-z])"),
    ("Skill Ops", r"(?<![A-Za-z])Skill\s+Ops(?![A-Za-z])"),
    ("Planning", r"(?<![A-Za-z])Planning(?![A-Za-z])"),
    ("Memory", r"(?<![A-Za-z])Memory(?![A-Za-z])"),
    (
        "Skill",
        r"(?<![A-Za-z])Skill(?!\s*(?:开发|选择|运维|运营|管理))(?![A-Za-z])",
    ),
    ("结构化输出", r"结构化输出"),
    ("多轮对话", r"多轮对话"),
    ("任务规划", r"任务规划"),
    ("状态管理", r"状态管理"),
    ("记忆机制", r"记忆机制"),
    ("多工具调用", r"多工具调用"),
    (
        "Tool Calling",
        (
            r"Tool\s*(?:Calling|Use)|Function\s*Calling|工具\s*/\s*函数调用|"
            r"工具调用|函数调用"
        ),
    ),
    ("AI Coding", r"AI\s*Coding"),
    ("Agent", r"(?<![A-Za-z])Agent(?:s)?(?![A-Za-z])|智能体"),
    (
        "LLM",
        r"(?<![A-Za-z])LLM(?:s)?(?![A-Za-z])|大语言模型(?:相关技术)?|大模型",
    ),
    ("NLP", r"(?<![A-Za-z])NLP(?![A-Za-z])|自然语言处理"),
    ("Transformer", r"Transformer"),
    ("GPT", r"(?<![A-Za-z])GPT(?![A-Za-z])"),
    ("BERT", r"(?<![A-Za-z])BERT(?![A-Za-z])"),
    ("模型架构", r"模型架构"),
    ("Linux", r"(?<![A-Za-z])Linux(?:\s*(?:开发|驱动))?(?![A-Za-z])"),
    ("Conda", r"(?<![A-Za-z])Conda(?![A-Za-z])"),
    ("Docker", r"Docker"),
    ("Kubernetes", r"Kubernetes|(?<![A-Za-z])K8s(?![A-Za-z])"),
    ("云原生开发", r"云原生开发"),
    ("CUDA", r"CUDA"),
    ("TensorRT-LLM", r"TensorRT[\s-]*LLM"),
    ("TensorRT", r"TensorRT(?![\s-]*LLM)"),
    ("vLLM", r"vLLM"),
    ("TVM", r"(?<![A-Za-z])TVM(?![A-Za-z])"),
    ("SGLang", r"SGLang"),
    ("MNN", r"(?<![A-Za-z])MNN(?![A-Za-z])"),
    ("NCNN", r"(?<![A-Za-z])NCNN(?![A-Za-z])"),
    ("llama.cpp", r"llama\.cpp"),
    ("PagedAttention", r"PagedAttention"),
    ("FlashAttention", r"FlashAttention"),
    ("Speculative Decoding", r"Speculative\s+Decoding"),
    ("KV-Cache", r"KV[\s-]*Cache"),
    ("Triton", r"(?<![A-Za-z])Triton(?![A-Za-z])"),
    ("MLIR", r"(?<![A-Za-z])MLIR(?![A-Za-z])"),
    ("RLlib", r"RLlib"),
    ("Stable-Baselines3", r"Stable[\s-]*Baselines3"),
    ("Acme", r"(?<![A-Za-z])Acme(?![A-Za-z])"),
    ("TensorFlow Agents", r"TensorFlow\s+Agents"),
    ("机器人仿真平台", r"(?:机器人)?仿真(?:训练)?(?:平台|环境)"),
    ("Isaac Sim", r"Isaac\s+Sim"),
    ("Isaac Gym", r"Isaac\s+Gym"),
    ("MuJoCo", r"MuJoCo"),
    ("PyBullet", r"PyBullet"),
    ("Genesis", r"(?<![A-Za-z])Genesis(?![A-Za-z])"),
    ("Unity", r"Unity"),
    ("Unreal Engine", r"Unreal(?:\s+Engine)?"),
    ("CMake", r"CMake"),
    ("计算机视觉", r"计算机视觉|图像算法|(?<![A-Za-z])CV(?![A-Za-z])"),
    ("图像处理", r"图像处理"),
    ("图像识别", r"图像识别|视觉[^。；\n]{0,8}识别|检测、识别"),
    ("语义分割", r"语义分割|识别、分割"),
    ("3D视觉", r"3D\s*视觉|三维视觉"),
    ("神经渲染", r"神经渲染"),
    ("生成模型", r"生成模型"),
    ("3DGS", r"(?<![A-Za-z0-9])3DGS(?![A-Za-z0-9])"),
    ("4DGS", r"(?<![A-Za-z0-9])4DGS(?![A-Za-z0-9])"),
    ("NeRF", r"(?<![A-Za-z])NeRF(?![A-Za-z])"),
    ("神经隐式表征", r"神经隐式表征"),
    ("Diffusion Policy", r"Diffusion\s+Policy"),
    ("Diffusion", r"(?<![A-Za-z])Diffusion(?![A-Za-z])|扩散模型"),
    ("视频生成", r"视频生成"),
    ("图像生成", r"图像生成"),
    ("可控生成", r"可控(?:视频)?生成"),
    ("场景编辑", r"场景编辑"),
    ("前端开发", r"前端开发(?:基础)?"),
    ("前后端开发", r"前后端开发"),
    ("目标检测", r"目标检测|视觉检测|^检测$"),
    ("视觉定位", r"视觉定位"),
    ("机器学习", r"机器学习"),
    ("深度学习", r"深度学习"),
    ("机器人学", r"机器人学(?!习)"),
    ("控制理论", r"控制理论"),
    ("强化学习", r"强化学习|(?<![A-Za-z])RL(?![A-Za-z])"),
    ("MDP", r"(?<![A-Za-z])MDP(?:建模)?(?![A-Za-z])"),
    ("策略梯度", r"策略梯度"),
    ("Actor-Critic", r"Actor[\s-]*Critic"),
    ("Self-Play", r"Self[\s-]*Play"),
    ("Meta-RL", r"Meta[\s-]*RL"),
    ("MARL", r"(?<![A-Za-z])MARL(?![A-Za-z])"),
    ("推荐系统", r"推荐系统|推荐算法"),
    ("搜索", r"搜索引擎|搜索算法"),
    ("数据结构与算法", r"数据结构(?:与|和)算法|数据结构、算法"),
    ("数据结构", r"数据结构"),
    ("图形学", r"图形学"),
    ("渲染", r"渲染"),
    ("计算机基础知识", r"计算机基础(?:知识)?"),
    ("编程基础", r"代码学习基础|编程基础"),
    ("编程能力", r"编程能力|代码能力"),
    ("面向对象编程", r"面向对象编程"),
    ("AI技术理解", r"(?:AI\s*)?(?:基本的?)?技术理解力"),
    ("软件工程", r"软件工程"),
    ("系统设计", r"系统设计"),
    ("模块开发", r"模块开发"),
    ("问题定位", r"问题定位|定位问题"),
    ("Bad Case 定位", r"Bad[\s-]*Case\s*定位"),
    ("异步编程", r"异步编程"),
    ("并发", r"并发(?:管理)?"),
    ("工程能力", r"工程能力"),
    ("软件质量", r"软件质量"),
    ("时序决策", r"时序决策"),
    ("跨场景泛化", r"跨场景泛化"),
    ("代码调试", r"代码调试|(?:独立完成)?[^。；\n]{0,8}调试"),
    ("模型训练平台", r"模型训练平台"),
    ("模型训练", r"模型训练(?!代码|平台)|训练能力"),
    ("深度学习框架原理", r"深度学习框架[^。；\n]{0,12}(?:架构|运行原理)"),
    ("大模型分布式训练", r"大模型训练[^。；\n]{0,16}(?:并行|分布式)"),
    ("推理引擎底层机制", r"推理引擎[^。；\n]{0,32}底层机制"),
    ("推理引擎源码开发", r"推理引擎[^。；\n]{0,40}(?:源码|二次开发)"),
    ("模型评测", r"模型评测|生成[-—–]评测|模型[^。；\n]{0,8}评估"),
    ("大规模数据处理", r"大规模数据处理"),
    ("实验设计", r"实验设计|设计(?:基本的)?\s*ablation\s*实验"),
    ("实验结果分析", r"分析[^。；\n]{0,12}实验结果"),
    ("训练环境", r"服务器训练环境|训练环境"),
    ("推理框架", r"推理(?:加速)?框架"),
    ("模型压缩", r"模型压缩(?:小型化)?"),
    ("模型轻量化", r"模型轻量化"),
    ("模型量化", r"模型(?:的)?量化|(?<!轻)量化"),
    ("模型剪枝", r"模型(?:的)?剪枝|剪枝"),
    ("模型蒸馏", r"模型(?:的)?蒸馏|蒸馏"),
    ("模型稀疏化", r"模型(?:的)?稀疏化|稀疏化"),
    ("GPU/NPU算子开发", r"GPU\s*/\s*NPU\s*算子开发"),
    ("端侧算法部署", r"端侧(?:硬件)?算法部署"),
    ("软硬件协同设计", r"软硬件(?:协同|联合)设计"),
    ("软硬件协同优化", r"软硬件(?:协同|联合)优化"),
    ("机器人运动学", r"机器人[^。；\n]{0,16}运动学"),
    ("机器人动力学", r"机器人[^。；\n]{0,16}动力学|运动学、动力学"),
    ("机器人部署", r"真实机器人(?:平台)?部署|机器人部署|真机部署"),
    ("机器人真机开发", r"机器人真机开发"),
    ("机器人控制", r"机器人控制"),
    ("机器人学习", r"机器人学习"),
    ("具身智能", r"具身智能"),
    ("ROS2", r"(?<![A-Za-z0-9])ROS2(?![A-Za-z0-9])"),
    ("ROS", r"(?<![A-Za-z0-9])ROS(?![A-Za-z0-9])"),
    ("Sim-to-Real", r"Sim(?:2|[-\s]*to[-\s]*)Real(?:迁移)?"),
    (
        "复杂多体系统强化学习运动控制",
        r"复杂多体系统的?强化学习运动控制",
    ),
    (
        "具身策略/VLA/Robot Policy",
        r"具身策略\s*/\s*VLA\s*/\s*Robot\s*Policy",
    ),
    ("Sensorimotor/灵巧操作", r"Sensorimotor\s*/\s*灵巧操作"),
    ("System 0/高频控制", r"System\s*0\s*/\s*高频控制"),
    (
        "机器人学习/Sim-to-Real",
        r"机器人学习\s*/\s*Sim(?:2|[-\s]*to[-\s]*)Real",
    ),
    ("大规模机器人数据", r"大规模(?:真实)?机器人数据"),
    ("大规模机器人策略训练", r"大规模机器人策略训练"),
    ("Robot Foundation Model", r"Robot\s+Foundation\s+Model"),
    ("World Model", r"World\s+Model|世界模型(?:\s*\+\s*策略)?"),
    ("Imitation Learning", r"Imitation\s+Learning|模仿学习"),
    ("Behavior Cloning", r"Behavior\s+Cloning"),
    ("Flow Matching", r"Flow\s+Matching"),
    ("Meta Learning", r"Meta\s+Learning"),
    ("VLA", r"(?<![A-Za-z])VLA(?![A-Za-z])"),
    ("VLM", r"(?<![A-Za-z])VLM(?![A-Za-z])"),
    ("ACT", r"(?<![A-Za-z])ACT(?![A-Za-z])"),
    ("LeRobot", r"LeRobot"),
    ("OpenVLA", r"OpenVLA"),
    ("Octo", r"(?<![A-Za-z])Octo(?![A-Za-z])"),
    ("灵巧手", r"灵巧手"),
    ("力觉/触觉", r"力觉\s*/\s*触觉|触觉或力觉|力觉或触觉"),
    ("双臂协作", r"双臂协作"),
    (
        "Contact-rich Manipulation",
        r"Contact[\s-]*rich\s+Manipulation",
    ),
    ("视觉-触觉融合", r"视觉\s*[-—–]\s*触觉融合"),
    ("触觉表征学习", r"触觉表征学习"),
    ("触觉感知", r"触觉感知"),
    ("接触操作", r"接触操作"),
    ("接触状态估计", r"接触状态估计"),
    ("滑移检测", r"滑移检测"),
    ("抓取稳定性预测", r"抓取稳定性预测"),
    ("力控制", r"力控制|强化学习控制"),
    ("阻抗控制", r"阻抗控制"),
    ("导纳控制", r"导纳控制"),
    ("模型预测控制", r"模型预测控制"),
    ("域随机化", r"域随机化"),
    (
        "多模态训练",
        r"多(?:模态|传感器|数据源)[^。；\n]{0,12}(?:混合)?训练",
    ),
    ("机器人数据采集", r"机器人数据采集(?:系统)?"),
    ("TAMP", r"任务与运动规划\s*TAMP|(?<![A-Za-z])TAMP(?![A-Za-z])"),
    ("Eigen", r"(?<![A-Za-z])Eigen(?![A-Za-z])"),
    ("NumPy", r"(?<![A-Za-z])NumPy(?![A-Za-z])"),
    ("MATLAB", r"(?<![A-Za-z])MATLAB(?![A-Za-z])"),
    ("Simulink", r"(?<![A-Za-z])Simulink(?![A-Za-z])"),
    ("Ansys", r"(?<![A-Za-z])Ansys(?![A-Za-z])"),
    ("Abaqus", r"(?<![A-Za-z])Abaqus(?![A-Za-z])"),
    ("Nastran", r"(?<![A-Za-z])Nastran(?![A-Za-z])"),
    ("HyperWorks", r"(?<![A-Za-z])HyperWorks(?![A-Za-z])"),
    ("LS-DYNA", r"(?<![A-Za-z])LS[-\s]*DYNA(?![A-Za-z])"),
    ("NX", r"(?<![A-Za-z])NX(?![A-Za-z])"),
    ("SolidWorks", r"SolidWorks"),
    ("Creo", r"(?<![A-Za-z])Creo(?![A-Za-z])"),
    ("数值计算", r"数值计算(?:方法)?"),
    ("Git", r"(?<![A-Za-z])Git(?![A-Za-z])"),
    ("Garak", r"(?<![A-Za-z])Garak(?![A-Za-z])"),
    ("API服务", r"API\s*服务"),
    ("数据Pipeline", r"数据\s*Pipeline"),
    ("数据清洗", r"数据清洗|数据采集、清洗"),
    ("数据去重", r"数据去重|清洗、去重"),
    ("大规模训练", r"大规模训练|(?:千|万)卡(?:级|规模)训练(?:系统)?"),
    ("低延迟推理", r"低延迟推理(?:系统)?"),
    ("系统编程", r"系统级编程|系统编程"),
    ("跨平台开发", r"跨平台(?:技术|开发)"),
    ("多端开发", r"多端开发"),
    ("全栈开发", r"全栈开发"),
    ("AI Coding工具使用", r"AI\s*Coding[^。；\n]{0,12}工具"),
    ("CPU架构", r"CPU\s*(?:体系结构|体系架构|架构)"),
    (
        "软件加固",
        r"软件加固|(?:安全防护[、,，]\s*)加固|加固(?=[、,，]\s*逆向工程)",
    ),
    ("分布式架构", r"分布式架构(?:设计)?"),
    ("半监督学习", r"半监督(?:学习)?"),
    ("自监督学习", r"自监督(?:学习)?"),
    ("主动学习", r"主动学习"),
    ("弱监督学习", r"弱监督(?:学习)?"),
    ("自动标注", r"自动化?标注"),
    ("数据标注", r"数据标注|^标注$"),
    ("OOM降级", r"OOM\s*降级"),
    ("GPU编程与优化", r"GPU\s*编程(?:与|和)优化"),
    ("算法实现", r"算法(?:的)?实现|实现(?:相关)?算法"),
    (
        "算法项目经验",
        r"参与过[^。；\n]{0,48}至少一类算法[^。；\n]{0,32}设计、仿真或验证",
    ),
    ("失效原因定位", r"失效(?:原因)?定位|定位(?:并分析)?失效原因"),
    ("双臂操作", r"双臂(?:协同)?操作"),
    ("多模态预训练", r"多模态预训练"),
    ("大模型视频理解", r"大模型[^。；\n]{0,16}视频(?:内容)?理解"),
    ("AI产品实践", r"AI\s*/?\s*大模型产品[^。；\n]{0,16}(?:实习|实践)"),
    ("数据集构建", r"数据集(?:构建|建设)"),
    ("RLHF", r"(?<![A-Za-z])RLHF(?![A-Za-z])"),
    ("RLVR", r"(?<![A-Za-z])RLVR(?![A-Za-z])"),
    (
        "世界模型复现",
        r"世界模型复现|(?:复现|主导)过?[^。；\n]{0,80}世界模型",
    ),
    ("开源框架贡献", r"开源框架[^。；\n]{0,100}(?:核心|实质性)?贡献"),
    (
        "Driving World Model",
        r"Driving(?:\s*/\s*Embodied)?\s+World\s+Model",
    ),
    (
        "Embodied World Model",
        r"(?:Driving\s*/\s*)?Embodied\s+World\s+Model",
    ),
    ("数据分析", r"数据分析"),
    ("基础安全隐私知识", r"基础安全隐私知识|安全隐私知识"),
    ("安全漏洞检测", r"安全漏洞[^；。\n]{0,24}检测"),
    ("隐私合规", r"隐私合规"),
    ("数据安全", r"数据安全"),
    ("个人信息保护", r"个人信息保护"),
    ("AI功能工程化实现", r"AI\s*功能(?:的)?\s*工程化实现"),
    ("AI基本原理", r"AI\s*基本原理"),
    ("API调用能力", r"API\s*调用能力"),
    ("算法复现", r"算法复现"),
    ("功能落地", r"功能落地"),
    (
        "AI能力边界理解",
        r"AI\s*能力(?:的)?\s*边界(?:与|和)?(?:应用潜力|可能性)?",
    ),
    (
        "AI产品/方案设计",
        r"AI\s*功能\s*设计|AI\s*(?:为核心(?:或|、)?\s*AI\s*增强型|增强型)?[^。；\n]{0,12}(?:产品|方案)",
    ),
    (
        "AI产品技术趋势",
        r"AI(?:产品)?\s*(?:技术)?(?:趋势|技术发展)|AI[^。；\n]{0,20}技术趋势",
    ),
    (
        "AI产品最佳实践",
        r"AI(?:产品)?\s*最佳实践|AI[^。；\n]{0,20}最佳实践",
    ),
    ("多模态学习", r"多模态学习"),
)

SKILL_CATEGORY_MEMBERS: dict[str, tuple[str, ...]] = {
    "编程语言": (
        "Python",
        "Java",
        "Go",
        "C++",
        "C#",
        "Rust",
        "JavaScript",
        "TypeScript",
        "SQL",
    ),
    "深度学习框架": ("PyTorch", "TensorFlow", "PaddlePaddle", "JAX"),
    "模型架构": ("Transformer", "GPT", "BERT"),
    "Web框架": ("FastAPI", "Flask", "Django"),
    "低代码平台": ("Coze", "Dify"),
    "Agent框架": (
        "LangChain",
        "LangGraph",
        "AutoGen",
        "LlamaIndex",
        "OpenAI Agents SDK",
        "OpenClaw",
        "Hermes",
        "Pi",
    ),
    "推理框架": (
        "TensorRT",
        "TensorRT-LLM",
        "vLLM",
        "TVM",
        "MNN",
        "NCNN",
        "llama.cpp",
    ),
    "强化学习框架": (
        "RLlib",
        "Stable-Baselines3",
        "Acme",
        "TensorFlow Agents",
    ),
    "机器人仿真平台": (
        "Isaac Sim",
        "Isaac Gym",
        "MuJoCo",
        "PyBullet",
        "Genesis",
    ),
    "环境管理工具": ("Conda", "Docker"),
    "三维设计软件": ("NX", "SolidWorks", "Creo"),
    "CAE工具使用": ("Ansys", "Abaqus", "Nastran", "HyperWorks", "LS-DYNA"),
    "游戏引擎": ("Unity", "Unreal Engine"),
    "ROS版本": ("ROS", "ROS2"),
    "跨平台开发": ("KMP", "RN"),
    "多端开发": ("iOS", "Android", "鸿蒙"),
}

_SKILL_CATEGORY_ALIASES: dict[str, str] = {
    "编程语言": "编程语言",
    "后端编程语言": "编程语言",
    "开发语言": "编程语言",
    "程序设计语言": "编程语言",
    "深度学习框架": "深度学习框架",
    "机器学习框架": "深度学习框架",
    "训练框架": "深度学习框架",
    "模型架构": "模型架构",
    "模型结构": "模型架构",
    "大模型架构": "模型架构",
    "web框架": "Web框架",
    "web开发框架": "Web框架",
    "低代码平台": "低代码平台",
    "agent框架": "Agent框架",
    "智能体框架": "Agent框架",
    "大模型agent框架": "Agent框架",
    "推理框架": "推理框架",
    "大模型推理框架": "推理框架",
    "模型推理框架": "推理框架",
    "推理引擎": "推理框架",
    "开源推理引擎": "推理框架",
    "大模型推理引擎": "推理框架",
    "强化学习框架": "强化学习框架",
    "rl框架": "强化学习框架",
    "机器人仿真平台": "机器人仿真平台",
    "机器人仿真框架": "机器人仿真平台",
    "仿真平台": "机器人仿真平台",
    "环境管理工具": "环境管理工具",
    "环境工具": "环境管理工具",
    "容器环境": "环境管理工具",
    "三维设计软件": "三维设计软件",
    "三维软件": "三维设计软件",
    "三维建模软件": "三维设计软件",
    "cae工具": "CAE工具使用",
    "cae工具使用": "CAE工具使用",
    "cae分析工具": "CAE工具使用",
    "游戏引擎": "游戏引擎",
    "主流游戏引擎": "游戏引擎",
    "ros版本": "ROS版本",
    "ros生态": "ROS版本",
    "跨平台技术": "跨平台开发",
    "跨平台开发": "跨平台开发",
    "多端开发": "多端开发",
    "多端开发项目": "多端开发",
    "agent技术领域": "Agent技术领域",
    "aiagent技术领域": "Agent技术领域",
    "应用构建经验": "应用构建经验",
    "对话系统/agent应用构建": "应用构建经验",
}

_SKILL_VALUE_ALIASES: dict[str, str] = {
    "加固": "软件加固",
    "技术理解力": "AI技术理解",
    "机器人时序决策": "时序决策",
    "机器人跨场景泛化": "跨场景泛化",
    "量化": "模型量化",
    "剪枝": "模型剪枝",
    "蒸馏": "模型蒸馏",
}

# Context-free aliases may be applied to already-atomic labels, including in
# evaluation. Keep contextual aliases such as mechanical/security "加固" in
# ``_SKILL_VALUE_ALIASES`` so they still require source evidence.
_ATOMIC_SKILL_VALUE_ALIASES: dict[str, str] = {
    "bc": "Behavior Cloning",
    "c/c++": "C++",
    "cpu体系结构": "CPU架构",
    "cpu体系架构": "CPU架构",
    "function calling": "Tool Calling",
    "golang": "Go",
    "js": "JavaScript",
    "linux 开发": "Linux",
    "linux驱动": "Linux",
    "linux 驱动": "Linux",
    "tool use": "Tool Calling",
    "ts": "TypeScript",
    "世界模型": "World Model",
    "ai相关项目": "AI项目",
    "ai智能体框架": "Agent框架",
    "bad case": "Bad Case 定位",
    "llm原理": "LLM",
    "multi-agent": "Multi-Agent",
    "prompt工程": "Prompt Engineering",
    "多agent": "Multi-Agent",
    "大模型": "LLM",
    "大模型后训练算法": "大模型后训练",
    "大模型规划": "Planning",
    "大规模数据去重": "数据去重",
    "基础大模型技术": "LLM",
    "对齐技术": "模型对齐",
    "对齐数据构建": "对齐数据",
    "工业级基础大模型研发经验": "工业级基础大模型研发",
    "分布式机器学习经验": "分布式机器学习",
    "工具调用": "Tool Calling",
    "对齐方法": "模型对齐",
    "微调方法": "模型微调",
    "编程": "编程能力",
    "微调": "模型微调",
    "模型coding": "Coding",
    "模型合并策略": "模型合并",
    "模型预训练": "大模型预训练",
    "监督学习方法": "监督学习",
    "稀疏模型架构": "稀疏模型",
    "规划": "Planning",
    "超长上下文建模": "长上下文建模",
    "数据使用策略": "数据策略",
    "数据提质": "数据质量",
    "合成数据构建": "合成数据",
    "模仿学习": "Imitation Learning",
    "扩散模型": "Diffusion",
    "工具/函数调用": "Tool Calling",
    "自动化标注": "自动标注",
    "机器学习理论": "机器学习",
    "深度学习理论": "深度学习",
    "transformer架构": "Transformer",
    "计算机基础": "计算机基础知识",
    "大语言模型原理": "LLM",
    "大语言模型方法": "LLM",
    "multi-agent系统": "Multi-Agent",
    "ai agent实践项目": "AI Agent项目",
    "multi-agent系统搭建实践经验": "Multi-Agent系统搭建",
    "agent落地应用经验": "Agent落地应用",
    "ai driven ide实践": "AI Driven IDE",
    "分布式系统基础": "分布式系统",
    "kubernetes基础原理": "Kubernetes",
    "工程素养": "工程能力",
    "k8s调度器": "kube-scheduler",
    "亲和性": "亲和性调度",
    "反亲和性": "反亲和性调度",
    "在离线混部": "在线离线混部",
    "有限元方法": "有限元",
    "结构件受力": "结构受力分析",
    "疲劳": "疲劳分析",
    "失效模式": "失效分析",
    "llm 基本原理": "LLM",
    "agent 基本原理": "Agent",
    "agent 开发": "Agent开发",
    "vlm 训练": "VLM训练",
    "主流 agent 框架": "Agent框架",
    "对话系统构建": "对话系统",
    "agent 应用构建": "Agent应用",
    "对齐": "模型对齐",
    "优化策略": "模型优化策略",
    "模型表现分析": "模型效果分析",
    "深度学习模型": "深度学习",
    "ai agent工具": "AI Agent工具使用",
    "ai agent相关实践项目": "AI Agent项目",
    "llm api调用": "LLM API",
    "大模型api调用": "LLM API",
    "大模型 api调用": "LLM API",
    "大模型 api 调用": "LLM API",
    "http协议": "HTTP",
    "http 协议": "HTTP",
    "工程实现能力": "工程实现",
    "上下文调试": "Context调试",
    "大语言模型": "LLM",
    "深度学习框架架构": "深度学习框架原理",
    "深度学习框架运行原理": "深度学习框架原理",
    "大模型训练多维并行架构": "大模型分布式训练",
    "底层机制": "推理引擎底层机制",
    "源码魔改": "推理引擎源码开发",
    "面向对象编程语言": "面向对象编程",
    "软件质量意识": "软件质量",
    "ai coding工具": "AI Coding工具使用",
    "具身智能项目经验": "具身智能项目",
    "ai 相关项目": "AI项目",
    "ai 相关项目经验": "AI项目",
    "llm技术原理": "LLM",
    "大模型项目": "LLM项目",
    "langchain经验": "LangChain",
    "garak经验": "Garak",
    "physical ai": "Physical AI安全",
    "具身智能安全": "Physical AI安全",
    "physical ai开源项目": "Physical AI安全开源项目",
    "具身智能安全开源项目": "Physical AI安全开源项目",
    "大模型研发经验": "LLM",
    "agent harness优化": "Agent Harness",
    "大语言模型相关技术": "LLM",
    "跨平台技术": "跨平台开发",
    "多智能体": "Multi-Agent",
    "大模型训练研究/项目经历": "大模型训练",
    "nlp研究/项目经历": "NLP项目",
    "电生理相关项目经历": "电生理信号项目",
    "电生理信号相关项目经历": "电生理信号项目",
    "ros框架": "ROS",
    "physical ai/具身智能安全": "Physical AI安全",
    "physical ai/具身智能安全开源项目": "Physical AI安全开源项目",
    "src漏洞": "漏洞挖掘",
    "结构件受力分析": "结构受力分析",
    "失效模式分析": "失效分析",
    "agent 应用": "Agent应用",
    "机器人关节/整机cae分析": "机器人CAE分析",
    "机器人关节cae分析": "机器人CAE分析",
    "机器人整机cae分析": "机器人CAE分析",
    "结构件疲劳": "疲劳分析",
    "结构件失效模式": "失效分析",
}

_GROUP_OPTION_ALIASES: dict[str, dict[str, str]] = {
    "系统基础": {
        "网络": "计算机网络",
    },
    "计算机基础": {
        "网络": "计算机网络",
    },
}

_CATEGORY_BY_SKILL = {
    member.casefold(): category
    for category, members in SKILL_CATEGORY_MEMBERS.items()
    for member in members
}

_CANONICAL_SKILL_BY_KEY = {
    canonical.casefold(): canonical for canonical, _ in SKILL_PATTERNS
}

_COMPOSITE_SKILL_PARENTS: dict[str, set[str]] = {
    "Agent": {
        "Agent Harness",
        "Agent Runtime",
        "Agent评测",
        "Agent系统研发",
        "Agent项目",
        "Agent系统上线",
        "机器人Agent",
        "工具调用Agent",
        "Coding Agent",
        "Search Agent",
        "Productivity Agent",
        "生产级Agent平台",
        "完整具身Agent项目",
        "具身Agent",
        "LLM Agent",
        "Agent Workflow",
        "多智能体系统",
        "Agent框架",
        "OpenAI Agents SDK",
        "TensorFlow Agents",
    },
    "TensorFlow": {"TensorFlow Agents"},
    "LLM": {
        "LLM Agent",
        "TensorRT-LLM",
        "LLM API",
        "大模型训练",
        "大模型后训练",
        "大模型应用",
    },
    "模型训练": {"大模型训练", "模型训练平台"},
    "数据库": {"向量数据库"},
    "Tool Calling": {"多工具调用", "工具调用Agent"},
    "Planning": {"Learning-based Planning", "Task Planning"},
    "Memory": {"Memory Retrieval"},
    "Skill": {"Skill Selection", "Skill Ops"},
    "强化学习": {"Agentic RL"},
    "具身Agent": {"完整具身Agent项目"},
    "Agent项目": {"完整具身Agent项目"},
    "渲染": {"神经渲染"},
    "Diffusion": {"Diffusion Policy"},
    "World Model": {
        "Driving World Model",
        "Embodied World Model",
        "世界模型复现",
    },
    "VLA": {"具身策略/VLA/Robot Policy"},
    "机器人学习": {"机器人学习/Sim-to-Real"},
    "力觉": {"力觉/触觉"},
    "触觉": {"力觉/触觉"},
    "数据结构": {"数据结构与算法"},
    "Sim-to-Real": {"机器人学习/Sim-to-Real"},
}

_SOFT_SKILL_PATTERN = re.compile(
    r"结构化思维|逻辑清晰|沟通|表达能力|团队协作|学习能力|自驱力|责任心|"
    r"好奇心|洞察力|审美|英语流利|问题分析与解决能力|综合素质|执行能力|"
    r"用户理解|产品体验|创造力|想象力|专业背景|学历要求",
)


@dataclass(frozen=True)
class SkillMatch:
    canonical: str
    source_text: str
    start: int
    end: int


@dataclass(frozen=True)
class NormalizedSkillConcept:
    """A locally-owned skill identity, independent of model wording."""

    skill_id: str
    canonical_name: str
    qualifier: SkillQualifier | None = None


def extract_skill_matches(value: str) -> list[SkillMatch]:
    """Extract known canonical skills in their source-text order."""

    matches: list[SkillMatch] = []
    for canonical, pattern in SKILL_PATTERNS:
        for match in re.finditer(pattern, value, flags=re.IGNORECASE):
            matches.append(
                SkillMatch(
                    canonical=canonical,
                    source_text=match.group(0),
                    start=match.start(),
                    end=match.end(),
                )
            )
    matches = [
        item
        for item in matches
        if not any(
            other.canonical in _COMPOSITE_SKILL_PARENTS.get(item.canonical, set())
            and
            other.start <= item.start
            and other.end >= item.end
            for other in matches
        )
    ]
    matches.sort(key=lambda item: (item.start, item.end, item.canonical))
    return matches


def extract_requirement_skill_matches(source_content: str) -> list[SkillMatch]:
    """Extract known skills from the requirement section of a JD."""

    return _unique_matches(extract_skill_matches(_requirement_text(source_content)))


def normalize_skill_values(
    values: Iterable[Any],
    *,
    keep_unknown: bool = True,
    source_text: str | None = None,
) -> list[str]:
    """Split model phrase-level skills into canonical, matchable labels."""

    labels: list[str] = []
    seen: set[str] = set()
    source_labels = (
        {match.canonical for match in extract_skill_matches(source_text)}
        if source_text is not None
        else set()
    )
    for value in values:
        if not isinstance(value, str):
            continue
        text = re.sub(r"\s+", " ", value).strip(" \t\r\n,，、;；")
        if not text or _SOFT_SKILL_PATTERN.search(text):
            continue

        exact_alias = _SKILL_VALUE_ALIASES.get(text.casefold())
        category = normalize_skill_category(text)
        matches = extract_skill_matches(text)
        if exact_alias is not None and exact_alias in source_labels:
            candidates = [exact_alias]
        elif category is not None:
            candidates = [category]
        elif matches:
            candidates = [match.canonical for match in matches]
        elif keep_unknown:
            candidates = [text]
        else:
            candidates = []

        for candidate in candidates:
            if candidate not in seen:
                labels.append(candidate)
                seen.add(candidate)
    if (
        source_text is not None
        and re.search(r"(?<![A-Za-z])C\s*/\s*C\+\+", source_text)
        and "C++" in seen
        and "C" in seen
    ):
        labels.remove("C")
    return labels


def normalize_atomic_skill_values(
    values: Iterable[Any],
    *,
    source_text: str | None = None,
) -> list[str]:
    """Canonicalize labels without decomposing an already-atomic concept.

    Core predictions and reviewed labels have already crossed an atomic-field
    boundary. Re-running substring extraction there would collapse distinct
    concepts such as ``AI Coding项目`` and ``AI Coding工具使用`` into the same
    parent label. Full-string pattern matches and explicit aliases remain safe.
    """

    labels: list[str] = []
    seen: set[str] = set()
    source_labels = (
        {match.canonical for match in extract_skill_matches(source_text)}
        if source_text is not None
        else set()
    )
    for value in values:
        if not isinstance(value, str):
            continue
        text = re.sub(r"\s+", " ", value).strip(" \t\r\n,，、;；")
        if not text or _SOFT_SKILL_PATTERN.search(text):
            continue

        category = normalize_skill_category(text)
        alias = _ATOMIC_SKILL_VALUE_ALIASES.get(text.casefold())
        contextual_alias = _SKILL_VALUE_ALIASES.get(text.casefold())
        canonical = _CANONICAL_SKILL_BY_KEY.get(text.casefold())
        evidence_base = re.sub(r"(?:经验|经历)$", "", text).strip()
        evidence_base_alias = _ATOMIC_SKILL_VALUE_ALIASES.get(
            evidence_base.casefold()
        )
        evidence_base_canonical = _CANONICAL_SKILL_BY_KEY.get(
            evidence_base.casefold()
        )
        if category is not None:
            candidates = [category]
        elif alias is not None:
            candidates = [alias]
        elif contextual_alias is not None and contextual_alias in source_labels:
            candidates = [contextual_alias]
        elif canonical is not None:
            candidates = [canonical]
        elif evidence_base_alias is not None:
            candidates = [evidence_base_alias]
        elif evidence_base_canonical is not None:
            candidates = [evidence_base_canonical]
        else:
            candidates = [text]

        for candidate in candidates:
            key = candidate.casefold()
            if key not in seen:
                labels.append(candidate)
                seen.add(key)
    if (
        source_text is not None
        and re.search(r"(?<![A-Za-z])C\s*/\s*C\+\+", source_text)
        and "c++" in seen
        and "c" in seen
    ):
        labels = [label for label in labels if label.casefold() != "c"]
    return labels


_SKILL_QUALIFIER_SUFFIXES: tuple[tuple[re.Pattern[str], SkillQualifier], ...] = (
    (
        re.compile(r"(?:相关)?开源(?:项目)?(?:经历|经验|实践)?$", re.IGNORECASE),
        "open_source_experience",
    ),
    (
        re.compile(r"(?:相关)?实习(?:经历|经验)?$", re.IGNORECASE),
        "internship_experience",
    ),
    (
        re.compile(r"(?:相关)?(?:科研|研究)(?:项目)?(?:经历|经验)?$", re.IGNORECASE),
        "research_experience",
    ),
    (
        re.compile(r"(?:相关)?研发(?:经历|经验)?$", re.IGNORECASE),
        "development_experience",
    ),
    (
        re.compile(r"(?:相关)?实践(?:经历|经验)?$", re.IGNORECASE),
        "practical_experience",
    ),
    (
        re.compile(r"(?:相关)?项目(?:经历|经验)?$", re.IGNORECASE),
        "project_experience",
    ),
)


def normalize_skill_concepts(
    value: Any,
    *,
    qualifier: SkillQualifier | None = None,
    source_text: str | None = None,
) -> list[NormalizedSkillConcept]:
    """Resolve one surface label to one or more stable local concepts.

    The model supplies surface skills and semantic qualifiers. Canonical names
    and IDs are generated here so prompt wording cannot create new identities.
    Legacy suffix labels remain supported for offline replay.
    """

    if not isinstance(value, str):
        return []
    surface = re.sub(r"\s+", " ", value).strip(" \t\r\n,，、;；")
    if not surface:
        return []
    base, inferred_qualifier = split_skill_qualifier(surface)
    resolved_qualifier = qualifier or inferred_qualifier

    explicit_alias = _ATOMIC_SKILL_VALUE_ALIASES.get(base.casefold())
    category = normalize_skill_category(base)
    if explicit_alias is not None:
        canonical_names = [explicit_alias]
    elif category is not None:
        canonical_names = [category]
    else:
        extracted = _unique_labels(match.canonical for match in extract_skill_matches(base))
        is_explicit_compound = bool(re.search(r"[/、,，]|\b(?:or|and)\b|或|以及", base, re.IGNORECASE))
        if len(extracted) >= 2 and is_explicit_compound:
            canonical_names = extracted
        else:
            canonical_names = normalize_atomic_skill_values(
                [base],
                source_text=source_text,
            )

    return [
        NormalizedSkillConcept(
            skill_id=skill_id_for(canonical_name),
            canonical_name=canonical_name,
            qualifier=resolved_qualifier,
        )
        for canonical_name in _unique_labels(canonical_names)
    ]


def split_skill_qualifier(
    value: str,
) -> tuple[str, SkillQualifier | None]:
    """Split legacy experience suffixes without treating them as skill names."""

    normalized = re.sub(r"\s+", " ", value).strip()
    for pattern, qualifier in _SKILL_QUALIFIER_SUFFIXES:
        match = pattern.search(normalized)
        if match is None:
            continue
        base = normalized[: match.start()].rstrip(" /_-、，,")
        if base:
            return base, qualifier
    return normalized, None


def skill_id_for(canonical_name: str) -> str:
    """Build a readable, deterministic ID from a locally canonical label."""

    token = unicodedata.normalize("NFKC", canonical_name).strip().casefold()
    token = token.replace("+", " plus ").replace("#", " sharp ")
    token = re.sub(r"[\W_]+", "-", token, flags=re.UNICODE).strip("-")
    return f"skill:{token}"


def build_skill_source_map(source_content: str) -> dict[str, str]:
    """Map canonical skills and provable upper categories to source fragments."""

    sources: dict[str, str] = {}
    for match in (
        *extract_requirement_skill_matches(source_content),
        *extract_skill_matches(source_content),
    ):
        sources.setdefault(match.canonical, match.source_text)
        category = skill_category_for(match.canonical)
        if category is not None:
            sources.setdefault(category, match.source_text)
    return sources


def normalize_skill_category(value: Any) -> str | None:
    """Return the shared canonical name for a supported skill category."""

    if not isinstance(value, str):
        return None
    normalized = re.sub(r"\s+", "", value).strip("：:，,、;；").casefold()
    return _SKILL_CATEGORY_ALIASES.get(normalized)


def skill_category_for(value: str) -> str | None:
    """Map a concrete canonical skill to its shared upper category."""

    labels = normalize_skill_values([value], keep_unknown=True)
    if len(labels) != 1:
        return None
    return _CATEGORY_BY_SKILL.get(labels[0].casefold())


def explicit_skill_categories(source_text: str) -> list[str]:
    """Return upper skill categories explicitly named in source text."""

    compact_source = re.sub(r"\s+", "", source_text).casefold()
    return _unique_labels(
        category
        for alias, category in _SKILL_CATEGORY_ALIASES.items()
        if alias in compact_source
    )


def normalize_skill_group(
    value: Any,
    *,
    options_are_atomic: bool = False,
) -> dict[str, Any] | None:
    """Normalize an ``any_of`` group without changing its OR semantics."""

    if not isinstance(value, dict):
        return None
    raw_options = value.get("any_of")
    if isinstance(raw_options, str):
        raw_options = [raw_options]
    if not isinstance(raw_options, list):
        return None
    options = (
        normalize_atomic_skill_values(raw_options)
        if options_are_atomic
        else normalize_skill_values(raw_options, keep_unknown=True)
    )
    if not options:
        return None

    raw_name = value.get("name")
    category = normalize_skill_category(raw_name)
    source_name = (
        category
        or (raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else None)
    )
    option_aliases = _GROUP_OPTION_ALIASES.get(source_name or "", {})
    options = [option_aliases.get(option.casefold(), option) for option in options]
    options = _unique_labels(options)
    option_categories = [skill_category_for(option) for option in options]
    inferred = _unique_labels(
        candidate for candidate in option_categories if candidate is not None
    )
    if (
        category is None
        and len(inferred) == 1
        and all(candidate is not None for candidate in option_categories)
    ):
        category = inferred[0]
    name = category or (raw_name.strip() if isinstance(raw_name, str) else "技能选项")
    return {
        "name": name,
        "any_of": options,
        "allow_other": bool(value.get("allow_other", False)),
    }


def normalize_skill_groups(
    values: Any,
    *,
    options_are_atomic: bool = False,
) -> list[dict[str, Any]]:
    """Normalize and merge duplicate skill groups while preserving order."""

    if not isinstance(values, list):
        return []
    groups: list[dict[str, Any]] = []
    indexes: dict[tuple[str, bool], int] = {}
    for value in values:
        group = normalize_skill_group(
            value,
            options_are_atomic=options_are_atomic,
        )
        if group is None:
            continue
        key = (group["name"].casefold(), group["allow_other"])
        if key not in indexes:
            indexes[key] = len(groups)
            groups.append(group)
            continue
        index = indexes[key]
        groups[index]["any_of"] = _unique_labels(
            [*groups[index]["any_of"], *group["any_of"]]
        )
    return groups


def normalize_skill_fields(
    payload: dict[str, Any],
    *,
    source_content: str | None = None,
) -> dict[str, Any]:
    """Normalize required/preferred skills before the domain model validates them.

    When requirements are present, they remain the source of truth. A grouped
    skill requirement is expanded into one requirement per canonical skill and
    reuses the original evidence, which remains a valid contiguous source
    fragment for every expanded item.
    """

    normalized = copy.deepcopy(payload)
    requirements = normalized.get("requirements")
    if isinstance(requirements, list):
        rebuilt: list[dict[str, Any]] = []
        for requirement in requirements:
            if not isinstance(requirement, dict):
                continue
            category = requirement.get("category")
            if category not in {"required_skill", "preferred_skill"}:
                rebuilt.append(requirement)
                continue

            evidence = requirement.get("evidence") or []
            evidence_texts = [
                item.get("source_text")
                for item in evidence
                if isinstance(item, dict)
            ]
            labels = normalize_skill_values(
                [requirement.get("name"), *evidence_texts],
                keep_unknown=False,
            )
            if not labels:
                labels = normalize_skill_values(
                    [requirement.get("name")],
                    keep_unknown=True,
                )
            if not labels:
                continue
            for label in labels:
                expanded = copy.deepcopy(requirement)
                expanded["name"] = label
                rebuilt.append(expanded)

        normalized["requirements"] = rebuilt
        for category, field_name in (
            ("required_skill", "required_skills"),
            ("preferred_skill", "preferred_skills"),
        ):
            labels = [
                item.get("name")
                for item in rebuilt
                if item.get("category") == category
                and isinstance(item.get("name"), str)
            ]
            if labels:
                normalized[field_name] = labels
            elif field_name in normalized:
                normalized[field_name] = None
    else:
        for field_name in ("required_skills", "preferred_skills"):
            value = normalized.get(field_name)
            if isinstance(value, list):
                normalized[field_name] = normalize_skill_values(value)

    groups = normalize_skill_groups(normalized.get("required_skill_groups"))
    if groups or "required_skill_groups" in normalized:
        normalized["required_skill_groups"] = groups or None
    mentions = normalized.get("skill_mentions")
    if isinstance(mentions, list):
        normalized["skill_mentions"] = normalize_skill_values(mentions)

    if source_content:
        _augment_required_skills_from_source(normalized, source_content)
    return normalized


def normalize_core_fields(
    payload: dict[str, Any],
    *,
    source_content: str,
) -> dict[str, Any]:
    """Normalize the lightweight Parser contract used by discovery/evaluation."""

    core_field_names = (
        "job_type",
        "locations",
        "required_skills",
        "required_skill_groups",
        "preferred_skills",
        "skill_mentions",
    )
    normalized: dict[str, Any] = {
        field_name: payload.get(field_name)
        for field_name in core_field_names
    }
    if isinstance(normalized["job_type"], str):
        normalized["job_type"] = normalized["job_type"].strip() or None
    locations = normalized["locations"]
    if isinstance(locations, str):
        locations = re.split(r"[/、,，;；|]", locations)
    if isinstance(locations, list):
        normalized["locations"] = _unique_labels(
            [
                item.strip()
                for item in locations
                if isinstance(item, str) and item.strip()
            ]
        ) or None
    for field_name in ("required_skills", "preferred_skills", "skill_mentions"):
        value = normalized.get(field_name)
        values = value if isinstance(value, list) else [value] if isinstance(value, str) else []
        normalized[field_name] = normalize_skill_values(
            values,
            keep_unknown=True,
        ) or None

    required_values, preferred_values = _demote_bonus_only_required_skills(
        normalized.get("required_skills") or [],
        normalized.get("preferred_skills") or [],
        source_content,
    )
    required_values, preferred_values = _promote_mandatory_preferred_skills(
        required_values,
        preferred_values,
        source_content,
    )
    required_values, low_strength_mentions = _demote_low_strength_required_skills(
        required_values,
        source_content,
    )
    required_values = _normalize_source_scoped_required_skills(
        required_values,
        source_content,
    )
    preferred_values = _augment_preferred_skills_from_source(
        preferred_values,
        source_content,
    )
    preferred_values = _normalize_source_scoped_preferred_skills(
        preferred_values,
        source_content,
    )
    preferred_values, preferred_example_mentions = _demote_preferred_examples(
        preferred_values,
        source_content,
    )
    preferred_values = _merge_preferred_composite_skills(
        preferred_values,
        source_content,
    )
    preferred_values = _drop_redundant_skill_parents(preferred_values)
    normalized["required_skills"] = _merge_composite_required_skills(
        required_values,
        source_content,
    ) or None
    groups = normalize_skill_groups(normalized.get("required_skill_groups"))
    (
        groups,
        ungrouped,
        ordinary_mentions,
        group_preferred,
    ) = _normalize_required_groups_against_source(groups, source_content)
    if ungrouped:
        normalized["required_skills"] = _unique_labels(
            [*(normalized.get("required_skills") or []), *ungrouped]
        )
    preferred_values = _unique_labels([*preferred_values, *group_preferred])
    preferred_values = _drop_redundant_skill_parents(preferred_values)
    normalized["preferred_skills"] = preferred_values or None
    collapsed_required, collapsed_mentions = _collapse_ordinary_category_skills(
        normalized.get("required_skills") or [],
        source_content,
    )
    normalized["required_skills"] = collapsed_required or None
    groups = _infer_required_skill_groups(
        _unique_labels(
            [
                *(normalized.get("required_skills") or []),
                *(normalized.get("skill_mentions") or []),
            ]
        ),
        groups,
        source_content,
    )
    groups = _recover_explicit_required_groups(groups, source_content)
    normalized["required_skill_groups"] = groups or None
    group_options = _unique_labels(
        option for group in groups for option in group["any_of"]
    )
    group_keys = {option.casefold() for option in group_options}

    required = [
        skill
        for skill in normalized.get("required_skills") or []
        if skill.casefold() not in group_keys
    ]
    required_keys = {skill.casefold() for skill in required}
    preferred = [
        skill
        for skill in normalized.get("preferred_skills") or []
        if skill.casefold() not in required_keys and skill.casefold() not in group_keys
    ]
    preferred_keys = {skill.casefold() for skill in preferred}
    mentions = _unique_labels(
        [
            *(normalized.get("skill_mentions") or []),
            *group_options,
            *ordinary_mentions,
            *collapsed_mentions,
            *low_strength_mentions,
            *preferred_example_mentions,
        ]
    )
    non_promotable_keys = group_keys | {
        skill.casefold()
        for skill in (
            *ordinary_mentions,
            *collapsed_mentions,
            *low_strength_mentions,
            *preferred_example_mentions,
        )
    }
    required, mentions = _promote_understood_required_skills(
        required,
        mentions,
        source_content,
    )
    required, mentions = _promote_strong_required_skills(
        required,
        mentions,
        non_promotable_keys,
        source_content,
    )
    required, mentions = _recover_explicit_required_skills(
        required,
        mentions,
        group_keys,
        source_content,
    )
    required, mentions = _demote_experiment_concepts(
        required,
        mentions,
        source_content,
    )
    required = _merge_composite_required_skills(required, source_content)
    required = _collapse_pipeline_steps(required, source_content)
    required_keys = {skill.casefold() for skill in required}
    preferred = [
        skill
        for skill in preferred
        if skill.casefold() not in required_keys and skill.casefold() not in group_keys
    ]
    preferred_keys = {skill.casefold() for skill in preferred}
    mentions = [
        skill
        for skill in mentions
        if skill.casefold() not in required_keys
        and skill.casefold() not in preferred_keys
    ]
    normalized["required_skills"] = required or None
    normalized["preferred_skills"] = preferred or None
    normalized["skill_mentions"] = mentions or None
    return normalized


def _promote_mandatory_preferred_skills(
    required_skills: list[str],
    preferred_skills: list[str],
    source_content: str,
) -> tuple[list[str], list[str]]:
    """Let an explicit mandatory clause win if a skill also appears as a bonus."""

    mandatory_text, _ = _split_requirement_sections(source_content)
    clauses = re.split(r"[。；;\n]", mandatory_text)
    promoted: list[str] = []
    for skill in preferred_skills:
        for clause in clauses:
            segment = _skill_clause_segment(skill, clause)
            if segment is None or re.search(
                r"优先|加分|bonus|preferred",
                segment,
                flags=re.IGNORECASE,
            ):
                continue
            if re.search(
                r"必须|掌握|熟悉|具备|精通|能够|能力|"
                r"实际使用|开发过|使用过|实践过|有.{0,20}经验",
                segment,
            ):
                promoted.append(skill)
                break

    promoted_keys = {skill.casefold() for skill in promoted}
    return (
        _unique_labels([*required_skills, *promoted]),
        [
            skill
            for skill in preferred_skills
            if skill.casefold() not in promoted_keys
        ],
    )


def _normalize_source_scoped_required_skills(
    required_skills: list[str],
    source_content: str,
) -> list[str]:
    """Resolve generic model labels only when the source fixes their meaning."""

    robot_motion_context = bool(
        re.search(
            r"机器人学与传统运控[^。；\n]{0,40}运动学、动力学",
            source_content,
        )
    )
    scientific_library_context = bool(
        re.search(
            r"熟悉\s*Eigen、NumPy\s*等科学计算库",
            source_content,
            flags=re.IGNORECASE,
        )
    )
    normalized: list[str] = []
    for skill in required_skills:
        if robot_motion_context and skill == "运动学":
            normalized.append("机器人运动学")
        elif robot_motion_context and skill == "动力学":
            normalized.append("机器人动力学")
        elif scientific_library_context and skill == "科学计算库":
            normalized.extend(("Eigen", "NumPy"))
        else:
            normalized.append(skill)
    return _unique_labels(normalized)


def _normalize_source_scoped_preferred_skills(
    preferred_skills: list[str],
    source_content: str,
) -> list[str]:
    """Resolve broad preferred labels when the source names a precise technology."""

    has_vector_database = bool(re.search(r"向量数据库", source_content))
    has_cloud_native_development = bool(re.search(r"云原生开发", source_content))
    normalized: list[str] = []
    for skill in preferred_skills:
        if has_vector_database and skill == "数据库":
            normalized.append("向量数据库")
        elif has_cloud_native_development and skill == "云原生":
            normalized.append("云原生开发")
        else:
            normalized.append(skill)
    return _unique_labels(normalized)


_INLINE_BONUS_SIGNAL = re.compile(
    r"优先|加分|bonus|preferred",
    flags=re.IGNORECASE,
)


def _augment_preferred_skills_from_source(
    preferred_skills: list[str],
    source_content: str,
) -> list[str]:
    """Expand selected categories and recover explicit bonus capabilities."""

    candidate_clauses = _bonus_clauses(source_content)
    result: list[str] = []
    for skill in preferred_skills:
        category = normalize_skill_category(skill)
        if category is None:
            result.append(skill)
            continue
        concrete = [
            match.canonical
            for clause in candidate_clauses
            if _skill_mentioned_in_text(skill, clause)
            for match in extract_skill_matches(clause)
            if skill_category_for(match.canonical) == category
        ]
        result.extend(concrete or [skill])
    if preferred_skills:
        result.extend(
            skill
            for skill, pattern in _EXPLICIT_PREFERRED_RECOVERY
            if any(
                re.search(pattern, clause, flags=re.IGNORECASE)
                for clause in candidate_clauses
            )
        )
    result.extend(
        skill
        for skill, pattern in _UNAMBIGUOUS_PREFERRED_RECOVERY
        if any(
            re.search(pattern, clause, flags=re.IGNORECASE)
            for clause in candidate_clauses
        )
    )
    return _unique_labels(result)


_EXPLICIT_PREFERRED_RECOVERY: tuple[tuple[str, str], ...] = (
    ("Agent项目", r"(?:完整的?\s*)?Agent[^。；\n]{0,32}项目经验"),
    ("Agent评测", r"(?:Agent|智能体)\s*(?:评测|评估)"),
    ("Agent系统上线", r"(?:真实)?上线运行的?\s*(?:AI\s*)?Agent\s*系统"),
    ("生产级Agent平台", r"生产级\s*Agent\s*平台"),
    ("世界模型复现", r"(?:复现|主导)过?[^。；\n]{0,80}世界模型类工作"),
    ("World Model", r"(?<![A-Za-z])World\s+Model(?![A-Za-z])"),
    ("VLA", r"(?<![A-Za-z])VLA(?![A-Za-z])"),
)


_UNAMBIGUOUS_PREFERRED_RECOVERY: tuple[tuple[str, str], ...] = (
    (
        "AI产品实践",
        r"AI\s*/?\s*大模型产品[^。；\n]{0,24}(?:实习|实践)经历",
    ),
    (
        "LLM",
        (
            r"(?:大模型|大语言模型)(?!产品|相关的?视频)"
            r"[^。；\n]{0,40}(?:项目|实习|科研|实践)|"
            r"(?:项目|实习|科研|实践)[^。；\n]{0,40}(?:大模型|大语言模型)"
        ),
    ),
    (
        "Agent",
        (
            r"(?:Agent|智能体)[^。；\n]{0,40}(?:项目|实习|科研|实践)|"
            r"(?:项目|实习|科研|实践)[^。；\n]{0,40}(?:Agent|智能体)"
        ),
    ),
    ("VLA", r"VLA[^。；\n]{0,32}(?:科研|项目)经验"),
    ("VLM", r"VLM[^。；\n]{0,32}(?:科研|项目)经验"),
    ("具身智能", r"具身智能[^。；\n]{0,32}(?:科研|项目)经验"),
    ("多模态预训练", r"多模态预训练[^。；\n]{0,20}经验"),
    ("模型蒸馏", r"蒸馏[^。；\n]{0,24}经验"),
    ("视频生成", r"视频生成[^。；\n]{0,24}经验"),
    ("模型轻量化", r"模型轻量化[^。；\n]{0,24}经验"),
    (
        "大模型视频理解",
        r"大模型[^。；\n]{0,24}视频(?:内容)?理解[^。；\n]{0,24}(?:项目|经验)",
    ),
    ("开源框架贡献", r"开源框架[^。；\n]{0,100}(?:核心|实质性)?贡献"),
    ("大规模训练", r"(?:千|万)卡(?:级|规模)训练(?:系统)?[^。；\n]{0,24}经验"),
    ("RLHF", r"(?<![A-Za-z])RLHF(?![A-Za-z])[^。；\n]{0,24}经验"),
    ("RLVR", r"(?<![A-Za-z])RLVR(?![A-Za-z])[^。；\n]{0,24}经验"),
    (
        "算法项目经验",
        r"参与过[^。；\n]{0,48}至少一类算法[^。；\n]{0,32}设计、仿真或验证",
    ),
    (
        "复杂多体系统强化学习运动控制",
        r"复杂多体系统的?强化学习运动控制经验者?优先",
    ),
    ("大规模机器人数据", r"大规模真实机器人数据[^。；\n]{0,20}经验"),
    ("灵巧手", r"有灵巧手、力觉\s*/\s*触觉、双臂协作或"),
    ("力觉/触觉", r"有灵巧手、力觉\s*/\s*触觉、双臂协作或"),
    (
        "Contact-rich Manipulation",
        (
            r"有灵巧手、力觉\s*/\s*触觉、双臂协作或\s*"
            r"Contact[\s-]*rich\s+manipulation经验"
        ),
    ),
)


_LOW_STRENGTH_REQUIREMENT = re.compile(
    r"了解|基础认知|有(?:一定|基本|较好)理解|基本理解|较好理解",
    flags=re.IGNORECASE,
)


def _demote_low_strength_required_skills(
    required_skills: list[str],
    source_content: str,
) -> tuple[list[str], list[str]]:
    """Move explicitly low-strength familiarity claims out of hard requirements."""

    mandatory_text, _ = _split_requirement_sections(source_content)
    clauses = [
        clause
        for clause in re.split(r"[。；;\n]", mandatory_text)
        if not _INLINE_BONUS_SIGNAL.search(clause)
    ]
    kept: list[str] = []
    demoted: list[str] = []
    for skill in required_skills:
        matching = [
            clause for clause in clauses if _skill_mentioned_in_text(skill, clause)
        ]
        if matching and all(
            _skill_occurrence_is_low_strength(skill, clause) for clause in matching
        ):
            demoted.append(skill)
        else:
            kept.append(skill)
    return kept, demoted


def _skill_occurrence_is_low_strength(skill: str, clause: str) -> bool:
    span = _skill_span_in_text(skill, clause)
    if span is None:
        return False
    preceding = [
        cue
        for cue in _REQUIREMENT_STRENGTH_CUE.finditer(clause)
        if cue.end() <= span[0]
    ]
    if preceding:
        return preceding[-1].lastgroup == "weak"
    return _LOW_STRENGTH_REQUIREMENT.search(clause[span[1] :]) is not None


_PREFERRED_NON_SKILL_PHRASE = re.compile(
    r"论文|会议发表|竞赛|技术影响力|强烈兴趣|从\s*0\s*到\s*1|实验报告写作",
    flags=re.IGNORECASE,
)

_PREFERRED_PROTECTED_SKILLS = {
    "Agent系统上线",
    "世界模型复现",
    "开源框架贡献",
    "计算机视觉",
    "多模态模型",
    "机器人数据采集",
}


def _demote_preferred_examples(
    preferred_skills: list[str],
    source_content: str,
) -> tuple[list[str], list[str]]:
    """Keep bonus capabilities separate from devices, tasks, and named examples."""

    clauses = _bonus_clauses(source_content)
    kept: list[str] = []
    mentions: list[str] = []
    for skill in preferred_skills:
        matching_clauses = [
            item for item in clauses if _skill_mentioned_in_text(skill, item)
        ]
        if not matching_clauses:
            kept.append(skill)
            continue
        non_skill_context = all(
            _PREFERRED_NON_SKILL_PHRASE.search(clause)
            and not re.search(r"项目|实习|科研|实践", clause)
            for clause in matching_clauses
        )
        if _PREFERRED_NON_SKILL_PHRASE.search(skill) or (
            non_skill_context and skill not in _PREFERRED_PROTECTED_SKILLS
        ):
            continue
        if any(
            _preferred_skill_is_example(skill, clause)
            for clause in matching_clauses
        ):
            mentions.append(skill)
            continue
        kept.append(skill)
    return _unique_labels(kept), _unique_labels(mentions)


def _preferred_skill_is_example(skill: str, clause: str) -> bool:
    if skill in _PREFERRED_PROTECTED_SKILLS:
        return False
    if re.search(r"世界模型类工作", clause) and re.search(r"复现|主导", clause):
        return True
    if re.search(r"开源框架", clause) and re.search(r"贡献", clause):
        return True
    if re.search(r"常见视觉任务", clause):
        return True
    if re.search(r"产品及框架", clause):
        return True
    if re.search(r"(?:触觉或力觉)?设备", clause):
        return True
    if re.search(r"接触丰富任务", clause):
        return True
    example = re.search(r"例如|比如", clause)
    if example is not None:
        compact_skill = re.sub(r"\s+", "", skill).casefold()
        compact_tail = re.sub(r"\s+", "", clause[example.end() :]).casefold()
        if compact_skill and compact_skill in compact_tail:
            return True
    return False


def _bonus_clauses(source_content: str) -> list[str]:
    mandatory_text, bonus_text = _split_requirement_sections(source_content)
    clauses = re.split(r"[。；;\n]", bonus_text) if bonus_text else []
    clauses.extend(
        clause
        for clause in re.split(r"[。；;\n]", mandatory_text)
        if _INLINE_BONUS_SIGNAL.search(clause)
    )
    return [clause.strip() for clause in clauses if clause.strip()]


def _merge_preferred_composite_skills(
    skills: list[str],
    source_content: str,
) -> list[str]:
    """Merge model-split labels when the bonus source expresses one composite."""

    keys = {skill.casefold() for skill in skills}
    if not {"力觉", "触觉"} <= keys or not re.search(
        r"力觉\s*/\s*触觉|力觉或触觉|触觉或力觉",
        source_content,
    ):
        return skills
    first_index = min(
        index
        for index, skill in enumerate(skills)
        if skill.casefold() in {"力觉", "触觉"}
    )
    merged = [skill for skill in skills if skill.casefold() not in {"力觉", "触觉"}]
    merged.insert(first_index, "力觉/触觉")
    return merged


def _drop_redundant_skill_parents(skills: list[str]) -> list[str]:
    keys = {skill.casefold() for skill in skills}
    return [
        skill
        for skill in skills
        if not any(
            child.casefold() in keys
            for child in _COMPOSITE_SKILL_PARENTS.get(skill, set())
        )
    ]


def _promote_understood_required_skills(
    required_skills: list[str],
    skill_mentions: list[str],
    source_content: str,
) -> tuple[list[str], list[str]]:
    """Treat an explicit requirement to understand a technology as mandatory."""

    mandatory_text, _ = _split_requirement_sections(source_content)
    clauses = re.split(r"[。；;\n]", mandatory_text)
    promoted: list[str] = []
    for skill in skill_mentions:
        for clause in clauses:
            segment = _skill_clause_segment(skill, clause)
            if segment is None or _GROUP_ALTERNATIVE_SIGNAL.search(segment):
                continue
            if re.search(r"或", segment):
                continue
            if re.search(r"(?:深入)?理解", segment) and not _LOW_STRENGTH_REQUIREMENT.search(
                clause
            ):
                promoted.append(skill)
                break
    promoted_keys = {skill.casefold() for skill in promoted}
    return (
        _unique_labels([*required_skills, *promoted]),
        [
            skill
            for skill in skill_mentions
            if skill.casefold() not in promoted_keys
        ],
    )


_REQUIREMENT_STRENGTH_CUE = re.compile(
    r"(?P<weak>包括但不限于|了解|基础认知|有(?:一定|基本|较好)理解|"
    r"基本理解|较好理解|优先|加分|bonus|preferred)|"
    r"(?P<strong>必须|熟练(?:掌握|使用)?|掌握|熟悉|精通|"
    r"(?:有|具有)?(?:深入|实际)理解|理解|具备|具有|能够|"
    r"实际使用|开发过|使用过|实践过)",
    flags=re.IGNORECASE,
)

_UNAMBIGUOUS_STRONG_SOURCE_RECOVERY = {
    "LLM Agent",
    "Agent Runtime",
    "Agent评测",
    "Bad Case 定位",
}
_KNOWN_SKILL_KEYS = {canonical.casefold() for canonical, _ in SKILL_PATTERNS}


def _promote_strong_required_skills(
    required_skills: list[str],
    skill_mentions: list[str],
    non_promotable_keys: set[str],
    source_content: str,
) -> tuple[list[str], list[str]]:
    """Promote skills scoped by a strong requirement cue, independent of model output."""

    mandatory_text, _ = _split_requirement_sections(source_content)
    clauses = re.split(r"[。；;\n]", mandatory_text)
    source_skills = [
        match.canonical
        for match in extract_skill_matches(mandatory_text)
        if match.canonical in _UNAMBIGUOUS_STRONG_SOURCE_RECOVERY
    ]
    candidates = _unique_labels(
        [
            *source_skills,
            *(
                skill
                for skill in skill_mentions
                if skill.casefold() in _KNOWN_SKILL_KEYS
            ),
        ]
    )
    required_keys = {skill.casefold() for skill in required_skills}
    promoted: list[str] = []
    for skill in candidates:
        if skill.casefold() in non_promotable_keys:
            continue
        category = skill_category_for(skill)
        if category is not None and category.casefold() in required_keys:
            continue
        if any(
            child.casefold() in required_keys
            for child in _COMPOSITE_SKILL_PARENTS.get(skill, set())
        ):
            continue
        if any(_strong_required_clause_supports(skill, clause) for clause in clauses):
            promoted.append(skill)

    promoted_keys = {skill.casefold() for skill in promoted}
    return (
        _unique_labels([*required_skills, *promoted]),
        [
            skill
            for skill in skill_mentions
            if skill.casefold() not in promoted_keys
        ],
    )


def _strong_required_clause_supports(skill: str, clause: str) -> bool:
    if (
        not clause.strip()
        or _INLINE_BONUS_SIGNAL.search(clause)
        or _GROUP_ALTERNATIVE_SIGNAL.search(clause)
        or re.search(r"包括但不限于|或", clause)
    ):
        return False

    span = _skill_span_in_text(skill, clause)
    if span is None:
        return False
    if _span_is_parenthetical(clause, span) or re.search(
        r"(?:例如|比如|如)[^。；;\n]{0,100}$",
        clause[: span[0]],
    ):
        return False
    if re.search(
        r"等[^，,。；;\n]{0,16}(?:算法|框架|平台|工具|模型|任务|方向)(?:相关)?",
        clause[span[1] :],
    ):
        return False
    cues = list(_REQUIREMENT_STRENGTH_CUE.finditer(clause))
    preceding = [cue for cue in cues if cue.end() <= span[0]]
    if preceding:
        nearest = preceding[-1]
        if nearest.lastgroup == "weak":
            return False
        if len(clause[nearest.end() : span[0]]) <= 160:
            return True

    tail = clause[span[1] : span[1] + 48]
    return bool(
        re.search(r"(?:有|具有)?(?:深入|实际)理解", tail)
        and not _LOW_STRENGTH_REQUIREMENT.search(tail)
    )


def _span_is_parenthetical(text: str, span: tuple[int, int]) -> bool:
    pairs = {"(": ")", "（": "）", "[": "]", "【": "】"}
    stack: list[str] = []
    for character in text[: span[0]]:
        if character in pairs:
            stack.append(pairs[character])
        elif stack and character == stack[-1]:
            stack.pop()
    return bool(stack)


_EXPLICIT_REQUIRED_RECOVERY: tuple[tuple[str, str], ...] = (
    ("编程语言", r"熟悉至少一门(?:主流)?编程语言"),
    ("软件工程", r"具备扎实的软件工程"),
    ("编程能力", r"软件工程与编程能力"),
    ("模型评测", r"独立完成[^。；\n]{0,32}评测[^。；\n]{0,12}链路"),
    ("实验结果分析", r"能够分析[^。；\n]{0,16}实验结果"),
    (
        "机器人部署",
        r"有真实机器人项目经验[^。；\n]{0,80}(?:真机|机器人)部署",
    ),
    ("问题定位", r"有真实机器人项目经验[^。；\n]{0,100}问题定位"),
    ("Agent Workflow", r"具备[^。；\n]{0,80}Agent\s+Workflow\s*工程经验"),
    ("具身Agent", r"完整具身\s*Agent\s*项目经验"),
    ("强化学习", r"精通强化学习[^。；\n]{0,80}策略梯度"),
    ("策略梯度", r"精通强化学习[^。；\n]{0,80}策略梯度"),
    ("Actor-Critic", r"精通强化学习[^。；\n]{0,80}Actor[\s-]*Critic"),
    ("Self-Play", r"精通强化学习[^。；\n]{0,80}Self[\s-]*Play"),
    ("Meta-RL", r"精通强化学习[^。；\n]{0,80}Meta[\s-]*RL"),
    ("MARL", r"精通强化学习[^。；\n]{0,80}(?<![A-Za-z])MARL"),
    ("系统编程", r"具备[^。；\n]{0,40}系统级编程"),
)


def _recover_explicit_required_skills(
    required_skills: list[str],
    skill_mentions: list[str],
    group_keys: set[str],
    source_content: str,
) -> tuple[list[str], list[str]]:
    """Recover a small set of unambiguous strong requirements from source."""

    mandatory_text, _ = _split_requirement_sections(source_content)
    recovered = [
        skill
        for skill, pattern in _EXPLICIT_REQUIRED_RECOVERY
        if skill.casefold() not in group_keys and re.search(pattern, mandatory_text)
    ]
    recovered_keys = {skill.casefold() for skill in recovered}
    return (
        _unique_labels([*required_skills, *recovered]),
        [
            skill
            for skill in skill_mentions
            if skill.casefold() not in recovered_keys
        ],
    )


_EXPERIMENT_CONCEPTS = {
    "baseline",
    "control group",
    "变量控制",
    "指标对比",
}


def _demote_experiment_concepts(
    required_skills: list[str],
    skill_mentions: list[str],
    source_content: str,
) -> tuple[list[str], list[str]]:
    if not re.search(
        r"理解[^。；\n]{0,48}(?:baseline|control group|变量控制|指标对比)",
        source_content,
        flags=re.IGNORECASE,
    ):
        return required_skills, skill_mentions
    demoted = [
        skill
        for skill in required_skills
        if skill.casefold() in _EXPERIMENT_CONCEPTS
    ]
    demoted_keys = {skill.casefold() for skill in demoted}
    return (
        [skill for skill in required_skills if skill.casefold() not in demoted_keys],
        _unique_labels([*skill_mentions, *demoted]),
    )


def _collapse_pipeline_steps(
    required_skills: list[str],
    source_content: str,
) -> list[str]:
    if "模型评测" not in required_skills or not re.search(
        r"重建\s*[-—–]\s*生成\s*[-—–]\s*评测[^。；\n]{0,12}链路",
        source_content,
    ):
        return required_skills
    return [
        skill for skill in required_skills if skill not in {"重建", "生成", "评测"}
    ]


def _demote_bonus_only_required_skills(
    required_skills: list[str],
    preferred_skills: list[str],
    source_content: str,
) -> tuple[list[str], list[str]]:
    """Move model-misclassified skills that occur only in the bonus section."""

    mandatory_text, bonus_text = _split_requirement_sections(source_content)
    if not bonus_text:
        return required_skills, preferred_skills

    kept: list[str] = []
    demoted: list[str] = []
    for skill in required_skills:
        if _skill_mentioned_in_text(skill, bonus_text) and not _skill_mentioned_in_text(
            skill,
            mandatory_text,
        ):
            demoted.append(skill)
        else:
            kept.append(skill)
    return kept, _unique_labels([*preferred_skills, *demoted])


_BONUS_SECTION_HEADING = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?"
    r"(?:[【\[]?[ \t]*(?:加分项|加分条件|优先条件|优先项|bonus|preferred)"
    r"[ \t]*[】\]]?|具备以下[^\n]{0,32}优先)"
    r"[ \t]*[：:]?[ \t]*$"
)

_INLINE_BONUS_SECTION_START = re.compile(
    r"(?im)^[ \t]*(?:\d+[.、][ \t]*)?"
    r"(?:加分项|加分条件|优先条件|优先项|bonus|preferred)[ \t]*[：:]",
)


def _split_requirement_sections(source_content: str) -> tuple[str, str]:
    requirement_text = _requirement_text(source_content)
    matches = [
        match
        for pattern in (_BONUS_SECTION_HEADING, _INLINE_BONUS_SECTION_START)
        if (match := pattern.search(requirement_text)) is not None
    ]
    if not matches:
        return requirement_text, ""
    match = min(matches, key=lambda item: item.start())
    return requirement_text[: match.start()], requirement_text[match.end() :]


def _skill_mentioned_in_text(skill: str, text: str) -> bool:
    key = skill.casefold()
    if key in {match.canonical.casefold() for match in extract_skill_matches(text)}:
        return True
    if re.fullmatch(r"[A-Za-z0-9 .+#/-]+", skill):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(skill)}(?![A-Za-z0-9])"
        return re.search(pattern, text, flags=re.IGNORECASE) is not None
    compact_skill = re.sub(r"\s+", "", skill).casefold()
    compact_text = re.sub(r"\s+", "", text).casefold()
    return bool(compact_skill) and compact_skill in compact_text


def _skill_span_in_text(skill: str, text: str) -> tuple[int, int] | None:
    skill_key = skill.casefold()
    for match in extract_skill_matches(text):
        if match.canonical.casefold() == skill_key:
            return match.start, match.end

    pattern = re.escape(skill)
    if re.fullmatch(r"[A-Za-z0-9 .+#/-]+", skill):
        pattern = rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])"
    fallback = re.search(pattern, text, flags=re.IGNORECASE)
    if fallback is None:
        return None
    fallback_span = fallback.span()
    if any(
        match.start <= fallback_span[0]
        and match.end >= fallback_span[1]
        and match.canonical.casefold() != skill_key
        for match in extract_skill_matches(text)
    ):
        return None
    return fallback_span


def _skill_clause_segment(skill: str, clause: str) -> str | None:
    span = _skill_span_in_text(skill, clause)
    if span is None:
        return None

    left = max(clause.rfind(delimiter, 0, span[0]) for delimiter in (",", "，"))
    right_candidates = [
        index
        for delimiter in (",", "，")
        if (index := clause.find(delimiter, span[1])) >= 0
    ]
    right = min(right_candidates) if right_candidates else len(clause)
    return clause[left + 1 : right]


def _split_top_level_comma_segments(value: str) -> list[str]:
    """Split comma-separated clauses while keeping parenthesized lists intact."""

    pairs = {"(": ")", "（": "）", "[": "]", "【": "】"}
    closing = set(pairs.values())
    stack: list[str] = []
    start = 0
    segments: list[str] = []
    for index, character in enumerate(value):
        if character in pairs:
            stack.append(pairs[character])
        elif character in closing and stack and character == stack[-1]:
            stack.pop()
        elif character in {",", "，"} and not stack:
            segment = value[start:index].strip()
            if segment:
                segments.append(segment)
            start = index + 1
    tail = value[start:].strip()
    if tail:
        segments.append(tail)
    return segments or [value]


def _group_allow_other(options: list[str], clause: str) -> bool:
    segments = _split_top_level_comma_segments(clause)
    _, local_segment = max(
        (
            sum(_skill_mentioned_in_text(option, segment) for option in options),
            segment,
        )
        for segment in segments
    )
    return bool(
        re.search(r"如|例如|包括但不限于|等|主流", local_segment)
        and not re.search(
            r"以下[^。；;\n]{0,32}(?:一个|一项)或多个",
            local_segment,
        )
    )


_GROUP_ALTERNATIVE_SIGNAL = re.compile(
    r"至少.{0,40}(?:一|1)(?:种|项|个|门)|"
    r"任(?:一|意一)(?:种|项|个|门)|任意|任选|"
    r"满足其中|其中.{0,8}即可|"
    r"(?:一|1)(?:种|项|个|门)或多(?:种|项|个|门)|之一",
    flags=re.IGNORECASE,
)


def _has_alternative_signal(
    options: list[str],
    clause: str,
    *,
    group_name: str | None = None,
) -> bool:
    """Return whether a choice signal actually scopes over the skill options."""

    spans = _option_spans(options, clause)
    if not spans:
        return False
    first_start = spans[0][0]
    last_end = spans[-1][1]
    for signal in _GROUP_ALTERNATIVE_SIGNAL.finditer(clause):
        if signal.start() <= first_start and signal.end() >= last_end:
            return True
        if signal.end() <= first_start:
            between = clause[signal.end() : first_start]
            if len(between) <= 120 and not re.search(r"[。；;]", between):
                return True
        elif signal.start() >= last_end:
            between = clause[last_end : signal.start()]
            if len(between) <= 40 and not re.search(r"[，,。；;\n]", between):
                return True
    for left, right in pairwise(spans):
        separator = clause[left[1] : right[0]]
        if re.search(r"或", separator):
            return True
        if "/" in separator and group_name != "编程语言":
            return True
    return bool(
        re.search(r"^.{0,12}或(?:其他|其它|任意)", clause[spans[-1][1] :])
    )


def _option_spans(options: list[str], clause: str) -> list[tuple[int, int]]:
    option_keys = {option.casefold() for option in options}
    spans: dict[str, tuple[int, int]] = {}
    for match in extract_skill_matches(clause):
        key = match.canonical.casefold()
        if key in option_keys:
            spans.setdefault(key, (match.start, match.end))
    for option in options:
        key = option.casefold()
        if key in spans:
            continue
        fallback = re.search(re.escape(option), clause, flags=re.IGNORECASE)
        if fallback is not None:
            spans[key] = fallback.span()
    return sorted(spans.values())


def _normalize_required_groups_against_source(
    groups: list[dict[str, Any]],
    source_content: str,
) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
    """Repair common model mistakes without inventing new group options."""

    mandatory_text, _ = _split_requirement_sections(source_content)
    kept: list[dict[str, Any]] = []
    ungrouped: list[str] = []
    ordinary_mentions: list[str] = []
    preferred: list[str] = []
    for group in groups:
        clause = _best_skill_clause(group["any_of"], mandatory_text)
        if clause:
            scoped_options, scoped_clause = _scope_group_options(
                group["any_of"],
                clause,
                group_name=group["name"],
            )
            scoped_keys = {option.casefold() for option in scoped_options}
            for option in group["any_of"]:
                if option.casefold() in scoped_keys:
                    continue
                segment = _skill_clause_segment(option, clause) or clause
                if _strong_required_clause_supports(option, segment):
                    ungrouped.append(option)
                else:
                    ordinary_mentions.append(option)
            group = {**group, "any_of": scoped_options}
            clause = scoped_clause
            group = _align_group_with_source_category(group, clause)
        if clause and _INLINE_BONUS_SIGNAL.search(clause):
            category = normalize_skill_category(group["name"])
            preferred.extend([category] if category else group["any_of"])
            continue
        has_alternative = bool(
            clause
            and _has_alternative_signal(
                group["any_of"],
                clause,
                group_name=group["name"],
            )
        ) or _has_alternative_signal(
            group["any_of"],
            mandatory_text,
            group_name=group["name"],
        )
        if group["name"] == "编程语言" and not has_alternative:
            ungrouped.extend(group["any_of"])
            continue
        if group["name"] == "机器人仿真平台" and not has_alternative:
            ungrouped.append("机器人仿真平台")
            ordinary_mentions.extend(group["any_of"])
            continue
        if not has_alternative:
            ordinary_mentions.extend(group["any_of"])
            continue
        if has_alternative and clause and len(group["any_of"]) >= 2:
            group = {
                **group,
                "allow_other": _group_allow_other(group["any_of"], clause),
            }
        kept.append(group)
    return (
        kept,
        _unique_labels(ungrouped),
        _unique_labels(ordinary_mentions),
        _unique_labels(preferred),
    )


def _scope_group_options(
    options: list[str],
    clause: str,
    *,
    group_name: str,
) -> tuple[list[str], str]:
    """Limit an alternative group to the comma segment carrying its choice cue."""

    segments = _split_top_level_comma_segments(clause)
    if len(segments) <= 1:
        return options, clause

    spans = _option_spans(options, clause)
    if spans:
        first_start = spans[0][0]
        last_end = spans[-1][1]
        if any(
            signal.start() <= first_start and signal.end() >= last_end
            for signal in _GROUP_ALTERNATIVE_SIGNAL.finditer(clause)
        ):
            return options, clause

    candidates: list[tuple[int, int, list[str], str]] = []
    for index, segment in enumerate(segments):
        local_options = [
            option for option in options if _skill_mentioned_in_text(option, segment)
        ]
        scoped_segment = segment
        if index > 0 and re.match(r"^\s*或", segment):
            preceding_options = [
                option
                for option in options
                if _skill_mentioned_in_text(option, segments[index - 1])
            ]
            local_options = _unique_labels([*preceding_options, *local_options])
            scoped_segment = f"{segments[index - 1]}，{segment}"
        elif index + 1 < len(segments) and re.search(r"或\s*$", segment):
            following_options = [
                option
                for option in options
                if _skill_mentioned_in_text(option, segments[index + 1])
            ]
            local_options = _unique_labels([*local_options, *following_options])
            scoped_segment = f"{segment}，{segments[index + 1]}"
        if len(local_options) < 2 or not _has_alternative_signal(
            local_options,
            scoped_segment,
            group_name=group_name,
        ):
            continue
        candidates.append(
            (len(local_options), -index, local_options, scoped_segment)
        )

    if not candidates:
        return options, clause
    _, _, scoped_options, scoped_clause = max(candidates, key=lambda item: item[:2])
    return scoped_options, scoped_clause


def _best_skill_clause(options: list[str], text: str) -> str:
    clauses = re.split(r"[。；;\n]", text)
    scored = [
        (sum(_skill_mentioned_in_text(option, clause) for option in options), clause)
        for clause in clauses
    ]
    score, clause = max(scored, default=(0, ""), key=lambda item: item[0])
    minimum_score = min(2, len(options))
    if score < minimum_score:
        return ""
    if _has_alternative_signal(options, clause):
        return clause
    segments = _split_top_level_comma_segments(clause)
    segment_score, segment = max(
        (
            sum(_skill_mentioned_in_text(option, item) for option in options),
            item,
        )
        for item in segments
    )
    return segment if segment_score >= minimum_score else clause


def _collapse_ordinary_category_skills(
    required_skills: list[str],
    source_content: str,
) -> tuple[list[str], list[str]]:
    """Collapse plain platform enumerations without inventing OR semantics."""

    simulation_skills = [
        skill
        for skill in required_skills
        if skill_category_for(skill) == "机器人仿真平台"
    ]
    if len(simulation_skills) < 2:
        return required_skills, []
    context = _best_skill_clause(simulation_skills, _requirement_text(source_content))
    if not context or _has_alternative_signal(simulation_skills, context):
        return required_skills, []
    if not re.search(r"仿真(?:训练)?(?:平台|环境)", context):
        return required_skills, []
    simulation_keys = {skill.casefold() for skill in simulation_skills}
    kept = [
        skill
        for skill in required_skills
        if skill.casefold() not in simulation_keys
    ]
    return _unique_labels([*kept, "机器人仿真平台"]), simulation_skills


def _merge_composite_required_skills(
    skills: list[str],
    source_content: str,
) -> list[str]:
    keys = {skill.casefold() for skill in skills}
    if {"llm", "agent"} <= keys and re.search(
        r"(?:深入理解|熟悉|掌握)[^。；\n]{0,24}LLM\s+Agent|"
        r"LLM\s+Agent[^。；\n]{0,40}(?:深入理解|熟悉|掌握)",
        source_content,
        flags=re.IGNORECASE,
    ):
        first_index = min(
            index
            for index, skill in enumerate(skills)
            if skill.casefold() in {"llm", "agent"}
        )
        skills = [
            skill
            for skill in skills
            if skill.casefold() not in {"llm", "agent"}
        ]
        skills.insert(first_index, "LLM Agent")
        keys = {skill.casefold() for skill in skills}
    if not {"数据结构", "算法"} <= keys or not re.search(
        r"数据结构\s*(?:与|和|、)\s*算法",
        source_content,
    ):
        return skills
    first_index = min(
        index
        for index, skill in enumerate(skills)
        if skill.casefold() in {"数据结构", "算法"}
    )
    merged = [
        skill
        for skill in skills
        if skill.casefold() not in {"数据结构", "算法"}
    ]
    merged.insert(first_index, "数据结构与算法")
    return merged


def _infer_required_skill_groups(
    candidate_skills: list[str],
    groups: list[dict[str, Any]],
    source_content: str,
) -> list[dict[str, Any]]:
    """Recover explicit OR/example groups if a model flattened their options."""

    grouped_keys = {
        option.casefold()
        for group in groups
        for option in group["any_of"]
    }
    by_category: dict[str, list[str]] = {}
    for skill in candidate_skills:
        category = skill_category_for(skill)
        if category is not None and skill.casefold() not in grouped_keys:
            by_category.setdefault(category, []).append(skill)

    requirement_text = _requirement_text(source_content)
    matches = extract_skill_matches(requirement_text)
    for category, options in by_category.items():
        if len(options) < 2:
            continue
        option_keys = {option.casefold() for option in options}
        first_matches: dict[str, SkillMatch] = {}
        for match in matches:
            key = match.canonical.casefold()
            if key in option_keys:
                first_matches.setdefault(key, match)
        option_matches = list(first_matches.values())
        if len({match.canonical.casefold() for match in option_matches}) < 2:
            continue
        if max(match.end for match in option_matches) - min(
            match.start for match in option_matches
        ) > 200:
            continue
        context = _best_skill_clause(options, requirement_text)
        if not context or _INLINE_BONUS_SIGNAL.search(context):
            continue
        options, context = _scope_group_options(
            options,
            context,
            group_name=category,
        )
        if len(options) < 2:
            continue
        explicit_alternative = _has_alternative_signal(
            options,
            context,
            group_name=category,
        )
        if not explicit_alternative:
            continue
        allow_other = bool(
            re.search(r"如|例如|包括但不限于|等|主流", context)
        )
        groups.append(
            {
                "name": category,
                "any_of": options,
                "allow_other": allow_other,
            }
        )
        grouped_keys.update(option_keys)
    return _recover_source_alternative_groups(
        normalize_skill_groups(groups),
        candidate_skills,
        source_content,
    )


_SOURCE_GROUP_NAMES: tuple[tuple[str, str], ...] = (
    (
        "机器学习推理训练框架",
        r"机器学习[^，,。；;\n]{0,12}(?:推理|训练)[^，,。；;\n]{0,8}框架",
    ),
    ("深度学习框架", r"深度学习框架"),
    ("编程语言", r"(?:主流)?(?:编程|开发)语言|一门主流语言"),
    ("三维设计软件", r"三维设计软件"),
    ("仿真工具", r"(?:主流)?仿真工具"),
    ("主流技术栈", r"主流技术栈"),
    ("模型项目方向", r"(?:CV|计算机视觉)\s*/\s*NLP\s*/\s*多模态(?:大)?模型"),
    ("理论研究方向", r"以下至少一个或多个领域"),
)


def _source_group_name_from_clause(clause: str) -> str | None:
    return next(
        (
            name
            for name, pattern in _SOURCE_GROUP_NAMES
            if re.search(pattern, clause, flags=re.IGNORECASE)
        ),
        None,
    )


def _align_group_with_source_category(
    group: dict[str, Any],
    clause: str,
) -> dict[str, Any]:
    """Prefer an explicit source category and remove subordinate examples."""

    source_name = _source_group_name_from_clause(clause)
    if source_name is None:
        return group
    options = list(group["any_of"])
    if source_name in SKILL_CATEGORY_MEMBERS:
        member_keys = {
            member.casefold() for member in SKILL_CATEGORY_MEMBERS[source_name]
        }
        member_count = sum(
            option.casefold() in member_keys for option in options
        )
        if member_count < min(2, len(options)):
            return group
    if source_name == "仿真工具":
        options = [
            option
            for option in options
            if not (
                (span := _skill_span_in_text(option, clause))
                and re.search(
                    r"\bwith\b[^，,。；;()（）]{0,48}$",
                    clause[: span[0]],
                    flags=re.IGNORECASE,
                )
            )
        ]
    return {
        **group,
        "name": source_name,
        "any_of": options or list(group["any_of"]),
    }


def _recover_source_alternative_groups(
    groups: list[dict[str, Any]],
    candidate_skills: list[str],
    source_content: str,
) -> list[dict[str, Any]]:
    """Recover explicit source choices even when the model emitted mentions."""

    candidate_keys = {skill.casefold() for skill in candidate_skills}
    mandatory_text, _ = _split_requirement_sections(source_content)
    recovered = list(groups)
    for clause in re.split(r"[。；;\n]", mandatory_text):
        for segment in _split_top_level_comma_segments(clause):
            if _INLINE_BONUS_SIGNAL.search(segment):
                continue
            option_matches = [
                match
                for match in _unique_matches(extract_skill_matches(segment))
                if match.canonical.casefold() in candidate_keys
                and normalize_skill_category(match.canonical) is None
                and not re.match(r"框架|语言|软件|技术栈", segment[match.end :])
            ]
            options = _unique_labels(match.canonical for match in option_matches)
            if len(options) < 2:
                continue

            group_name = _source_group_name_from_clause(segment)
            inferred_categories = _unique_labels(
                category
                for option in options
                if (category := skill_category_for(option)) is not None
            )
            if group_name is None and len(inferred_categories) == 1:
                group_name = inferred_categories[0]
            if group_name is None:
                continue

            if group_name in SKILL_CATEGORY_MEMBERS:
                member_keys = {
                    member.casefold()
                    for member in SKILL_CATEGORY_MEMBERS[group_name]
                }
                options = [
                    option for option in options if option.casefold() in member_keys
                ]
            aligned_group = _align_group_with_source_category(
                {
                    "name": group_name,
                    "any_of": options,
                    "allow_other": False,
                },
                segment,
            )
            group_name = aligned_group["name"]
            options = aligned_group["any_of"]
            if len(options) < 2 or not _has_alternative_signal(
                options,
                segment,
                group_name=group_name,
            ):
                continue

            option_keys = {option.casefold() for option in options}
            new_group = {
                "name": group_name,
                "any_of": options,
                "allow_other": bool(
                    re.search(
                        r"如|例如|包括但不限于|等|主流",
                        segment,
                    )
                ),
            }
            overlapping_indexes = [
                index
                for index, group in enumerate(recovered)
                if len(
                    {option.casefold() for option in group["any_of"]}
                    & option_keys
                )
                >= 2
            ]
            if overlapping_indexes:
                existing_option_keys = {
                    option.casefold()
                    for index, group in enumerate(recovered)
                    if index in overlapping_indexes
                    for option in group["any_of"]
                }
                if not existing_option_keys <= option_keys:
                    continue
                insert_index = min(overlapping_indexes)
                recovered = [
                    group
                    for index, group in enumerate(recovered)
                    if index not in overlapping_indexes
                ]
                recovered.insert(min(insert_index, len(recovered)), new_group)
            else:
                recovered.append(new_group)
    return normalize_skill_groups(recovered)


_EXPLICIT_REQUIRED_GROUP_RECOVERY: tuple[
    tuple[str, tuple[str, ...], str, int],
    ...,
] = (
    (
        "触觉/接触基础",
        ("触觉感知", "接触操作"),
        r"(?:机器人)?触觉感知\s*或\s*接触操作[^。；\n]{0,20}(?:基础经验|基本理解|熟悉|掌握)",
        2,
    ),
    (
        "机器人算法基础",
        ("机器学习", "深度学习", "机器人学", "控制理论"),
        r"具备扎实的机器学习、深度学习、机器人学或控制理论基础",
        2,
    ),
    (
        "任务与运动规划方向",
        ("TAMP", "符号推理", "几何推理", "Learning-based Planning"),
        (
            r"掌握任务与运动规划\s*TAMP、符号推理、几何推理或\s*"
            r"Learning-based\s+Planning\s*至少一个方向"
        ),
        2,
    ),
    (
        "具身Agent项目经历",
        (
            "完整具身Agent项目",
            "LeRobot",
            "Open X-Embodiment",
            "GR00T",
            "Meta-World",
            "CALVIN",
        ),
        (
            r"完整具身\s*Agent\s*项目经验，或参与过\s*LeRobot、"
            r"Open\s+X-Embodiment、GR00T、Meta-World、CALVIN\s*等开源项目"
        ),
        2,
    ),
    (
        "Agent系统经历",
        ("Agentic RL", "工具调用Agent", "多智能体系统"),
        r"有\s*Agentic\s+RL、工具调用\s*Agent\s*或多智能体系统的发表或上线记录",
        1,
    ),
)


def _recover_explicit_required_groups(
    groups: list[dict[str, Any]],
    source_content: str,
) -> list[dict[str, Any]]:
    """Recover narrowly defined OR groups with explicit source alternatives."""

    mandatory_text, _ = _split_requirement_sections(source_content)
    recovered = list(groups)
    for name, options, pattern, replacement_overlap in (
        _EXPLICIT_REQUIRED_GROUP_RECOVERY
    ):
        option_keys = frozenset(option.casefold() for option in options)
        if not re.search(pattern, mandatory_text, flags=re.IGNORECASE):
            continue
        replaced_indexes = [
            index
            for index, group in enumerate(recovered)
            if len(
                {option.casefold() for option in group["any_of"]} & option_keys
            )
            >= replacement_overlap
        ]
        recovered = [
            group
            for group in recovered
            if len(
                {option.casefold() for option in group["any_of"]} & option_keys
            )
            < replacement_overlap
        ]
        insert_index = min(replaced_indexes, default=len(recovered))
        recovered.insert(
            min(insert_index, len(recovered)),
            {
                "name": name,
                "any_of": list(options),
                "allow_other": False,
            },
        )
    return normalize_skill_groups(recovered)


def _augment_required_skills_from_source(
    payload: dict[str, Any],
    source_content: str,
) -> None:
    """Recover explicit technical terms the model omitted from its skill list."""

    # Keep an entirely empty model result as an honest null parse. Source
    # augmentation is a recall aid after the model has entered the skill or
    # requirements path, not a replacement for the Parser's field decision.
    if not payload.get("required_skills") and not payload.get("requirements"):
        return

    requirement_text = _requirement_text(source_content)
    matches = _unique_matches(extract_skill_matches(requirement_text))
    if not matches:
        return

    existing = [
        value
        for value in payload.get("required_skills") or []
        if isinstance(value, str)
    ]
    known_existing = normalize_skill_values(existing, keep_unknown=False)
    labels = _unique_labels(
        [*(match.canonical for match in matches), *known_existing]
    )

    requirements = payload.get("requirements")
    if not isinstance(requirements, list):
        requirements = []
    filtered_requirements: list[dict[str, Any]] = []
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        if requirement.get("category") != "required_skill":
            filtered_requirements.append(requirement)
            continue
        if normalize_skill_values(
            [requirement.get("name")],
            keep_unknown=False,
        ):
            filtered_requirements.append(requirement)
    requirements = filtered_requirements
    required_by_name = {
        item.get("name"): item
        for item in requirements
        if item.get("category") == "required_skill"
        and isinstance(item.get("name"), str)
    }
    for match in matches:
        if match.canonical in required_by_name:
            continue
        required_by_name[match.canonical] = {
            "category": "required_skill",
            "name": match.canonical,
            "description": f"岗位原文明确提到 {match.source_text}",
            "mandatory": True,
            "evidence": [
                {
                    "field_path": "requirements[]",
                    "source_text": match.source_text,
                }
            ],
        }
    non_required = [
        item
        for item in requirements
        if item.get("category") != "required_skill"
    ]
    ordered_required = [
        required_by_name[label]
        for label in labels
        if label in required_by_name
    ]
    for index, requirement in enumerate(
        ordered_required,
        start=len(non_required),
    ):
        for evidence in requirement.get("evidence") or []:
            if isinstance(evidence, dict):
                evidence["field_path"] = f"requirements[{index}]"
    payload["requirements"] = [*non_required, *ordered_required]
    payload["required_skills"] = labels

    field_evidence = payload.get("field_evidence")
    if not isinstance(field_evidence, list):
        field_evidence = []
        payload["field_evidence"] = field_evidence
    has_skill_evidence = any(
        isinstance(item, dict)
        and (
            item.get("field_path") == "required_skills"
            or str(item.get("field_path", "")).startswith("required_skills[")
        )
        for item in field_evidence
    )
    if not has_skill_evidence:
        field_evidence.append(
            {
                "field_path": "required_skills",
                "source_text": matches[0].source_text,
            }
        )


def _requirement_text(source_content: str) -> str:
    headings = re.finditer(
        r"任职要求|岗位要求|职位要求|资格要求|招聘要求|课题要求|AI能力要求",
        source_content,
    )
    starts = [match.start() for match in headings]
    return source_content[min(starts) :] if starts else ""


def _unique_matches(matches: Iterable[SkillMatch]) -> list[SkillMatch]:
    result: list[SkillMatch] = []
    seen: set[str] = set()
    for match in matches:
        if match.canonical in seen:
            continue
        result.append(match)
        seen.add(match.canonical)
    return result


def _unique_labels(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
