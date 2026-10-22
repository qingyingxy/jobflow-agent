from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-06"
PREREGISTRATION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_4_generalization_holdout_"
    "preregistration_v1_2026-09-06.json"
)
PREREGISTRATION_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_4_generalization_holdout_"
    "preregistration_freeze_v1_2026-09-06.json"
)
PRIOR_INDEPENDENT_SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_independent_holdout_"
    "selection_v1_2026-09-06.json"
)
SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_4_generalization_holdout_"
    "selection_v1_2026-09-06.json"
)
INDEPENDENCE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_4_generalization_holdout_"
    "independence_receipt_v1_2026-09-06.json"
)
SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_4_generalization_holdout_"
    "source_freeze_v1_2026-09-06.json"
)

EXPECTED_STRATA = {
    "C1-knowledge-positive": 1,
    "C2-motivation-positive": 1,
    "Z1-zero-lower-bound-positive": 1,
    "C0-formal-category-negative-control": 1,
    "Z0-positive-lower-bound-negative-control": 1,
}
EXPECTED_FLOORS = {
    "v44-generalization-ntu-ai-engineer-data-infra": 11,
    "v44-generalization-jobgether-mlops-field-engineer": 14,
    "v44-generalization-brattle-data-ai-engineer": 13,
    "v44-generalization-fastmarkets-ai-engineer": 20,
    "v44-generalization-expedia-principal-data-ai-engineer": 11,
}
FROZEN_QUERY_ORDER = [
    "site:myworkdayjobs.com AI engineer knowledge of",
    "site:jobs.workable.com AI engineer knowledge of",
    "site:jobs.lever.co AI engineer motivation curiosity passion",
    "site:job-boards.greenhouse.io AI engineer 0-3 years",
    "site:jobs.smartrecruiters.com AI engineer skills capabilities",
    "site:careers.* AI engineer 2+ years",
]


BODY_C1 = """AI Engineer, Data Infra

Location: NTU Main Campus, Singapore
Employment type: Full time
Posted: 8 Days Ago
Job requisition id: R00025373

AI Singapore (AISG) is a national AI programme launched by the National Research Foundation (NRF), Singapore, to build and anchor deep national capabilities in AI.  AISG is supported through a government-wide partnership including the NRF, Ministry of Digital Development and Information (MDDI), Infocomm Media Development Authority (IMDA), Economic Development Board (EDB) and Enterprise Singapore (ESG). We bring together research institutions and the vibrant ecosystem of AI start-ups and companies to support impactful research, develop talent, and power Singapore's AI efforts.

This position will be hosted at Nanyang Technological University (NTU) under VP (Artificial Intelligence & Digital Economy)’s office and we welcome you to join our community.

We're looking for an AI Engineer to join the Platform team within AI Products at AISG. In this role, you will design, build, and scale the data infrastructure that powers large language model (LLM) training, fine-tuning, evaluation, and retrieval-augmented generation (RAG) across the organisation. Your work will directly contribute to the architecture and reliability of data storage systems, data pipelines, and the compute infrastructure that supports large-scale AI workloads.

Responsibilities:

Data infrastructure and architecture

Develop and maintain the overall data architecture, ensuring it scales to support AI training, fine-tuning, evaluation, and RAG workloads.

Define and manage the data technology stack, evaluating and adopting tools that best fit evolving data needs.

Build automation for data transfer and backup, and support data cataloging/discovery tools.

Design and maintain data pipelines (batch and streaming) using tools like AWS Glue and Amazon EMR.

Data governance and management

Architect and govern org-level IAM policy across AWS Organizations including SCPs, cross-account roles, and permission boundaries to enforce least-privilege access at scale.

Review and enhance data access patterns for performance and cost optimization.

Develop and manage data analytics and dashboarding capabilities using tools like Amazon Athena and QuickSight to give stakeholders visibility into platform usage and cost.

AI-assisted ops and continuous improvement

Use AI tools (e.g. Claude, Copilot, Cursor) appropriately in your daily work responsibilities.

Build internal tools leveraging AI to reduce manual effort in day-to-day operations.

Requirements:

You should be a hands-on engineer who enjoys both building robust infrastructure and designing tools that other engineers and researchers want to use. You should be comfortable balancing platform ownership (architecture, cost, governance) with product thinking (usability, self-service, adoption).

A degree in Computer Science, Information Technology, or equivalent.

At least 2–4 years of data infrastructure, platform or systems engineering experience, with a track record of operating production systems at scale.

Strong knowledge of distributed data systems and storage technologies (object storage, data lakes, distributed file systems, vector databases) and data pipelining tools (e.g. Apache Spark, Apache Airflow, Ray, Dagster).

Working knowledge of data access control and data orchestration.

Familiarity with cloud organisational structures (e.g. AWS Organizations, GCP folder/project hierarchy), including multi-account/multi-project setups, org-level IAM, and billing/cost allocation.

Hands-on experience operating workloads on different cloud providers including IaC (e.g. Terraform), containers and orchestration (e.g. Docker, Kubernetes), and managed services for compute, storage, and networking.

Demonstrated use of AI tools (e.g. Claude, Copilot, Cursor) in your day-to-day engineering — for code generation, review, debugging, and documentation — with a clear sense of where they help and where they don't.

Solid scripting/programming skills (e.g. Python, SQL) and comfortable reading other people's code across the stack.

Strong communication skills and a team collaborator.

Good to Have:

Experience with LLM training dataset (e.g. Common Crawl).

C/C++/Rust/Go or other relevant programming languages.

Contributions to open-source AI/ML projects.

We regret that only shortlisted candidates will be notified.

Hiring Institution: NTU"""
BODY_C2 = """MLOps Field Engineer

Location: France
Employment type: Full-time
Workplace: Remote

This position is listed on behalf of a partner company, who manages all applications and next steps. Our partner is looking for a MLOps Field Engineer based in France.

Join a global Field Engineering team helping organizations adopt modern AI and machine learning technologies across public and private cloud environments.
You will design and deliver sophisticated ML and data architectures using Linux, Kubernetes, and leading open-source technologies.
The role combines technical consulting, solution architecture, customer engagement, and hands-on implementation rather than traditional software development.
You will solve complex challenges involving distributed training, large-scale data processing, real-time analytics, and high-performance AI workloads.
Working closely with sales and technical teams, you will translate customer requirements into scalable, practical infrastructure solutions.
You will also influence product direction by sharing customer insights and technical feedback with engineering and product teams.
This is an opportunity to work directly with customers while gaining hands-on exposure to emerging AI, MLOps, cloud, and open-source technologies.

Accountabilities:
Architect cloud infrastructure and AI/ML solutions using technologies such as Kubernetes, Kubeflow, OpenStack, Spark, and public cloud platforms.
Work across the Linux technology stack, including networking, storage, infrastructure, virtualization, containers, and applications.
Design and deliver solutions for both on-premises environments and public clouds such as AWS, Azure, and Google Cloud.
Gather customer business and technical requirements and recommend appropriate open-source technologies and infrastructure solutions.
Deploy, test, validate, and hand over technical solutions to support or managed services teams following project completion.
Deliver technical presentations, demonstrations, architecture discussions, and training sessions for prospective and existing customers.
Collaborate closely with sales teams to develop solutions that address customer requirements and contribute to shared commercial objectives.
Provide technical feedback to product and engineering teams based on customer requirements, implementation experience, and emerging market needs.
Contribute to a healthy, collaborative engineering culture by sharing knowledge, supporting colleagues, and promoting effective technical practices.
Develop and maintain Python-based solutions and Kubernetes operators where required to support infrastructure and automation initiatives.
Travel internationally for customer meetings, industry events, internal events, and project-related activities, with travel potentially reaching up to 30% of working time.

Requirements:

Bachelor’s degree in a technical discipline or a compelling alternative professional background.
Experience in data engineering, MLOps, analytics, or deployment of big data solutions.
Practical experience with a programming language such as Python, R, or Rust, with intermediate Python skills expected.
Hands-on knowledge of Linux, virtualization, containers, networking, and cloud computing concepts.
Experience with Kubernetes and familiarity with cloud platforms such as AWS, Azure, or Google Cloud.
Understanding of large-scale enterprise open-source technologies, private clouds, machine learning, AI, data platforms, and analytics.
Experience designing, deploying, or operating technical solutions in customer-facing environments is valuable.
Strong business-minded problem-solving skills and the ability to translate technical challenges into practical solutions.
Excellent written and spoken English, with strong presentation and interpersonal communication skills.
Confidence to exchange feedback, contribute ideas, challenge assumptions respectfully, and collaborate with diverse stakeholders.
Strong curiosity, flexibility, accountability, self-motivation, and commitment to continuous learning.
A proactive, results-oriented approach with the ability to manage commitments and adapt quickly to new projects.
Passion for technology demonstrated through professional work, personal projects, or other technical initiatives.
Familiarity with Linux, particularly Debian or Ubuntu, is preferred.
Ability to work effectively within distributed, multicultural, and multinational teams.
Willingness and ability to travel internationally, including for events lasting up to two weeks and customer or industry meetings.

Benefits:

Distributed work environment with twice-yearly in-person team sprints.
Personal learning and development budget of USD 2,000 per year.
Annual compensation review based on location, experience, and performance.
Performance-driven annual bonus or commission.
Recognition rewards.
40 days of annual leave per year, including public holidays and company-wide holiday periods.
Maternity and paternity leave.
Team Member Assistance Program and Wellness Platform.
Opportunities to travel internationally and meet colleagues in different locations.
Priority Pass and travel upgrades for long-haul company events.
Hands-on exposure to AI/ML infrastructure, MLOps, Kubernetes, cloud platforms, data engineering, and open-source technologies.
Opportunities to work directly with customers across different industries and solve complex, real-world technical challenges.
Continuous learning opportunities across emerging technologies, distributed systems, data platforms, and AI infrastructure."""
BODY_Z1 = """Data and AI Engineer

Location: Boston, Massachusetts, United States

The Brattle Group, a privately held, global economics consulting firm, is looking for a Data and AI Engineer to join our Boston, MA office.

The Data & AI Engineer is an early-career role within Brattle’s Data & AI Engineering team, focused on hands-on technical work across client delivery, applied R&D, and internal capability-building. This role is designed for candidates who are strong builders, fast learners, and clear communicators, and who want to develop technical judgment in a setting where problems are varied, ambiguous, and often time-sensitive.

This is not a narrowly defined pipeline role or a heads-down engineering track. Data & AI Engineers work across data engineering, applied analytics, machine learning, and AI-enabled workflows, staying close to implementation while learning how technical choices affect real client work.

Candidates are not expected to arrive as experts across data engineering, solution architecture, and applied AI research. They are expected to be hands-on, curious, coachable, and comfortable learning quickly.

 

Where This Role Sits at Brattle:

The Data & AI Engineering team is a specialized technical group embedded within Brattle’s consulting staff. The team supports client work while also serving as an applied R&D function for the firm: researching emerging technologies, prototyping new analytical and AI-enabled workflows, and translating useful methods into reusable capabilities.

The team partners with economists, consultants, industry experts, and internal stakeholders to improve how the firm works with data, analytics, machine learning, and AI through project delivery, reusable tools, documentation, training, and knowledge-sharing.

Data & AI Engineers work under the guidance of more experienced technical leads, including Senior Data & AI Engineers, Solutions Architects, and Research Engineers. As experience grows, the role can develop toward deeper execution ownership, increased responsibility for solution design, more advanced AI and research work, or some combination of those paths.

 

Nature of the Work:

Data & AI Engineers work on problems where the technical path is often unclear, the data is imperfect, and the constraints are real. Source materials may be incomplete, inconsistent, degraded through prior systems, or difficult to interpret. Some matters also involve restricted or confidential workflows that shape how data can be accessed, handled, or shared.

The role requires practical judgment. There may be multiple valid approaches, each with trade-offs, and limited ability to go back to the source for clarification. Data & AI Engineers are expected to reason carefully from imperfect inputs, document assumptions, surface limitations, and help build solutions that are defensible, reproducible, timely, and fit for purpose.

Project timelines may shift quickly based on external events, negotiations, litigation deadlines, or client needs. Some work is recurring and operational; some is one-off or exploratory. The right candidate is a resourceful, practical builder: someone who can stay organized, adapt to changing constraints, and make progress without losing rigor or composure.

The team environment is academic, collegial, grounded, and highly collaborative. We value curiosity, humility, initiative, clear communication, and practical intelligence. The work can be technically advanced, but the culture is not ego-driven. We are looking for people who are resourceful, friendly, proactive, flexible, and able to work well with others in a global, connected consulting environment.

 

Some of the day-to-day responsibilities of this role include:

Prepare, inspect, clean, reconstruct, and validate data from a wide range of sources, including structured datasets, documents, reports, exports, PDFs, scans, and other formats that may not have been created for analysis
Use Python, SQL, notebooks, version control, and related tools to build reproducible workflows, test assumptions, troubleshoot issues, and document how work was performed
Identify data limitations, quality issues, assumptions, blockers, and open questions early
Support applied analytics, machine learning, and AI-enabled workflows where they are useful to the problem
Contribute to workflows involving text extraction, classification, summarization, embeddings, retrieval-augmented generation, model evaluation, automation, visualization, or rapid prototyping
Use AI tools thoughtfully to accelerate learning and execution while maintaining responsibility for accuracy, confidentiality, defensibility, and quality
Support applied R&D by helping prototype, test, and evaluate new tools, methods, and workflows before they are adopted more broadly
Communicate progress, technical findings, assumptions, limitations, and trade-offs clearly to consultants, economists, technical peers, and other stakeholders
Participate in code review, collaborative problem solving, documentation, and iterative refinement of work products
Help turn lessons from project work and applied R&D into reusable team assets, examples, templates, documentation, and training materials

You will not be expected to own full workstreams on day one, but you will be expected to learn quickly, take initiative, and stretch beyond a narrow technical lane.

 

THE CANDIDATE

Bachelor’s degree in Computer Engineering, Computer Science, Data Science, Applied Mathematics, Statistics, Economics with strong technical coursework, or a related field
Equivalent hands-on technical experience, internships, research work, or project-based experience may also be considered
0-3 years of professional experience in data engineering, analytics, applied AI, machine learning, software development, research, or related technical work
Demonstrated interest in using AI tools, machine learning methods, or automation to solve practical problems, with willingness to learn how to evaluate those tools responsibly
Comfort working in ambiguous problem spaces where the task may need to be clarified, decomposed, and revised as new information emerges
Strong foundation in Python for data analysis, scripting, automation, or prototyping, with exposure to libraries such as pandas, NumPy, scikit-learn, or comparable tools
Working knowledge of SQL and relational data concepts, including joins, aggregation, filtering, and practical data exploration
Foundational understanding of statistics, data analysis, machine learning, or experimental evaluation, with interest in strengthening applied judgment over time
Exposure to generative AI workflows, such as prompt design, embeddings, vector search, retrieval-augmented generation, summarization, classification, or model evaluation
Ability to work with structured, semi-structured, and unstructured data, including text-heavy documents or heterogeneous data sources
Familiarity with software development practices such as Git, notebooks, code review, documentation, testing, and reproducible workflows
Familiarity with cloud platforms such as Azure or comparable environments is helpful but not required
Ability to learn new tools quickly and use AI-assisted development responsibly without treating generated output as automatically correct
Strong written and verbal communication skills, including the ability to explain technical work, assumptions, limitations, and next steps clearly
Ability to manage multiple parallel workstreams in a fast-paced environment
Flexible mindset to adapt to changing project priorities and client needs.

 

Brattle offers a competitive benefits package, base salary, and bonus program for eligible roles based on individual and firm performance. The anticipated base gross salary range for this position in Boston, MA is $105,000 - $115,000 annually.  Actual salary will depend on a variety of factors, including experience and training.

 

This position is not eligible for immigration sponsorship.

 

EQUAL OPPORTUNITY

The Brattle Group is an Equal Opportunity Employer.  All qualified applicants will receive consideration for employment without regard to race, color, creed, religion, citizenship status, national origin, ancestry, sex, gender identity and expression, age, height, weight, domestic partner status, Acquired Immune Deficiency Syndrome or HIV status (AIDS/HIV status), genetic information, sexual orientation, disability (where the applicant or employee is qualified to perform the essential functions of the job with or without reasonable accommodation), marital status, veteran status, political affiliation, drug or alcohol abuse or alcoholism, or any other characteristic protected under applicable law.

 

We encourage all applicants to click here to review our full Equal Employer Opportunity Statement.

 

THE EMPLOYER"""
BODY_Z1 += (
    "\n\nThe Brattle Group answers complex economic, finance, and regulatory "
    "questions for corporations, law firms, and governments around the world. "
    "We are distinguished by the clarity of our insights and the credibility "
    "of our experts, which include leading international academics and industry "
    "specialists. "
    "Brattle has 500 talented professionals across North America, Europe, and "
    "Asia-Pacific. For more information, please visit brattle.com."
)
BODY_C0 = """AI Engineer

Company: Fastmarkets
Location: Sofia, Bulgaria
Employment type: Full-time, Permanent
Workplace: Hybrid

Company Description

Fastmarkets is an industry-leading price-reporting agency (PRA) and information provider for global commodities, providing price data, news, analytics and events for the agriculture, forest products, metals and mining and new-generation energy markets.

Fastmarkets' data is critical for customers seeking to understand and predict dynamic, sometimes opaque markets, enabling trading and risk management. Fastmarkets is a global business with a history dating back to 1865 and is built on trust and deep market knowledge. It has more than 700 employees spread across global locations in the UK, US, China, India, Singapore, Brazil, Belgium, Bulgaria, Finland and beyond. 

Job Description

The Role

The Fastmarkets Innovation & AI team sits within the Technology function and is responsible for developing and delivering the company’s AI and data strategy through agentic AI systems, intelligent data applications, and AI-powered analytics. The team has built a modern data platform and is actively shipping AI capabilities across the business—from agentic request intake systems to natural language data exploration tools powered by LLMs and semantic models.

Reporting directly into the Head of AI Enablement, we are looking for an AI Engineer to design, build, and ship AI-powered applications and features. This is a fantastic opportunity to join us and contribute to a high-performing workstream delivering transformational AI capabilities across both internal tools and monetizable data assets. You will work with cutting-edge AI technologies—Anthropic Claude, Snowflake Cortex AI, semantic models, and agentic frameworks—to build systems that enable users to interact with data and insights in entirely new ways.

The AI Engineer will take responsibility for the full lifecycle of AI features: from designing agents and LLM-powered workflows, to connecting them to data via pipelines and semantic models, to shipping polished user-facing applications. You will ensure that AI systems are reliable, observable, and deliver measurable business value.

We actively leverage AI tools across the engineering workflow, including Anthropic Claude for code generation, design, and review, and Snowflake Cortex AI capabilities for in-platform intelligence. The successful candidate will be expected to embrace AI-assisted development as a core part of how we work.

The role requires a high standard of expertise in Python and TypeScript/JavaScript, as well as specialist knowledge of LLMs, prompt engineering, agentic systems, and semantic data modelling. You should be comfortable working across the full stack—from designing LLM-powered backends to building modern React frontends.

Principal Accountabilities

· Design and develop agentic AI systems that solve real business problems—request intake agents, natural language query systems, intelligent data exploration tools, and AI-powered search and analysis features

· Integrate LLMs into applications using best practices: prompt engineering, tool use, multi-turn conversation management, output validation, and cost optimisation

· Build semantic models and data schemas that enable natural language querying over enterprise data (Snowflake Cortex Analyst, custom RAG systems)

· Connect AI systems to data pipelines: design how data flows from source → transformation → semantic layer → AI application, ensuring freshness, quality, and lineage are observable

· Develop full-stack AI applications: Next.js frontends with streaming chat UIs, FastAPI/Python backends for agentic workflows, and server-side integration with LLMs and data platforms

· Implement observability and evaluation frameworks for AI systems—structured logging, conversation tracing, golden evals, and adversarial verification of agent behaviour

· Work with modern orchestration and deployment patterns: containerised on-demand environments, Snowflake SPCS, CI/CD pipelines, and infrastructure-as-code

· Write production-grade Python and TypeScript: follow code-first practices, maintain strict type safety, build testable systems with clear separation of concerns

· Embrace AI-assisted development: use Claude for code generation, architecture design, and code review to accelerate delivery without compromising quality

· Identify and promote best practices in AI engineering: recommend improvements to prompting strategies, evaluation methodology, data schema design, and system reliability

· Excellent problem-solving skills and ability to embrace change—AI is a rapidly evolving field; you should be curious, experimental, and comfortable with ambiguity

· Effective communication and collaboration skills: you’ll work cross-functionally with data engineers, product teams, and business stakeholders to translate requirements into shipped AI features

· Natural self-starter, with enthusiasm for learning and research: staying current with the latest in LLMs, prompt engineering, and agentic systems is essential

KEY INTERFACES

Internal:

· Head of AI Enablement

· Data Engineering team (for data pipeline and schema design)

· Technology & Infrastructure teams

· Product and Commercial teams

· BI & Analytics teams & stakeholders across the business

External:

· Anthropic technical partnerships team

· Snowflake technical account team

· Cloud platform providers (Azure, AWS, Snowflake)

· Third-party vendor and tooling support

 

Qualifications

We recruit talented, dynamic people with diverse backgrounds and experiences, all united by a belief in our mission to provide the world’s leading and most trusted price reporting, events, and intelligence service for the markets we serve. We’re proud to be an equal opportunities employer and are committed to creating a fully inclusive workplace, where everyone feels able to participate and contribute meaningfully.

If you are open-minded, curious, resilient, solutions-oriented and committed to promoting equality, then read on.

KNOWLEDGE, EXPERIENCE AND SKILLS

We are looking for an individual who is highly motivated, driven, and have a passion to be part of a fast-paced, successful team. Being a strong team player is also important as well as someone who is happy to work flexibly.

Essential

· Advanced Python expertise – async/await, dependency injection, structured logging, testing patterns, Python type hints (Pydantic v2). Experience building production API services (FastAPI, Django, Flask).

· TypeScript / JavaScript expertise – React 18+, Next.js (App Router, Server Components), async state management, type-safe API clients. Comfortable with modern frontend patterns and server-driven rendering.

· LLM and prompt engineering knowledge – multi-turn conversation design, tool use and function calling, prompt optimisation, output parsing and validation, cost and latency considerations, understanding of model capabilities and limitations.

· Familiarity with agentic AI frameworks – experience building or working with agents, ReAct patterns, tool-calling loops, planning and reasoning, constraint satisfaction. Can implement agent loops from scratch using the Anthropic SDK.

· Snowflake expertise – SQL (CTEs, stored procedures, query tuning), Snowflake-specific features (Snowpark for Python transformations, zero-copy cloning, containerised compute). Knowledge of Cortex AI capabilities (Cortex Analyst, embeddings, vector search) is highly desirable.

· Semantic data modelling – designing data schemas and semantic layers that enable natural language queries. Understanding of fact tables, dimensions, metrics, and how LLMs reason over structured data. Familiarity with Cortex Analyst YAML or similar semantic modelling approaches.

· API integration and data transformation – working with REST/GraphQL APIs, JSON/Protocol Buffer parsing, data validation, designing robust connectors that handle edge cases and errors gracefully.

· Git version control – branching strategies, pull requests, merge conflict resolution, atomic commits, clear commit messages.

· CI/CD principles and experience – GitHub Actions, test automation, deployment pipelines, infrastructure-as-code mindset.

· Cloud services experience – Azure, AWS, or GCP. Ability to identify and configure suitable cloud services and resources.

· Solid understanding of data modelling approaches – fact tables, dimensions, normalisation, and denormalisation tradeoffs. How to structure data to serve both analytics and AI use cases.

· Excellent analytical and problem-solving skills – you can diagnose why an agent is failing, why a semantic model isn’t returning the right results, or why a data pipeline isn’t fresh.

· Strong communication skills with attention to detail – you can explain AI system design decisions to non-technical stakeholders and write clear documentation.

Desirable

· Experience with Anthropic Claude and the Anthropic Python SDK – hands-on work building agentic systems or multi-turn applications.

· Snowflake Cortex Analyst experience – designing semantic models, writing YAML, iterating on metrics and dimensions for NL query accuracy.

· Semantic search and RAG – building retrieval-augmented generation systems, vector databases, embedding strategies, and hybrid search (lexical + semantic).

· Container orchestration and Kubernetes – deploying containerised services, understanding networking, resource management, scaling patterns.

· Infrastructure as Code – Terraform, Pulumi, or similar, defining cloud resources as code.

· Event streaming and real-time data – Apache Kafka, Azure Service Bus, or similar; designing systems that react to data changes in near-real-time.

· Evaluation frameworks for AI systems – golden datasets, adversarial testing, metric definition, A/B testing of prompts or models.

· Data quality and observability – implementing automated checks, monitoring, and alerting for both data pipelines and AI systems. Familiarity with tools like dbt, Great Expectations.

· Exposure to CRM systems (Salesforce) and marketing platforms (Marketo).

· Experience shipping full-stack AI applications – end-to-end responsibility from data → AI backend → user-facing frontend.

Formal Qualifications

· Degree in Computer Science, Engineering, Mathematics, or related technical field OR 3+ years’ professional experience building AI systems, data applications, or production ML systems

· Can demonstrate experience working on a project that delivered transformational change or exceptional business value – or a personal AI/data project that required significant research, learning, and execution (e.g. a bot, data analysis tool, RAG system, semantic search application)

· Certifications in Snowflake, cloud platforms, or LLM engineering are a nice-to-have but not required.

If you're excited about the role but your experience, skills or qualifications don't perfectly align, we encourage you to apply anyway.

Additional Information

Our Values

Fastmarkets people come from all different walks of life. It’s this mix of brilliant personalities, experiences and insights that gives us that warm, open, and friendly culture you can feel as soon as you meet us. But however wonderfully different we all are, there are six things we all have in common – and they form our Fastmarkets values.

Created by our own employees to reflect some of the personal traits that Fastmarkets people have, our values are key to what makes our culture unique. They reflect who each of us are and they're embedded in everything we do. Our values are:

METRICS DRIVEN. We use insights to improve our customers’ experience and our business performance
ACCOUNTABLE. We are accountable to ourselves and those we work with: we keep our promises and get things done
GROWTH MINDSET. This value enables us to be nimble to the changing realities and operate with a sense of urgency
INCLUSIVE. We are inclusive and respectful, celebrating each of us and giving everyone a deep sense of belonging with the desire to bring their best self to work every day.
CUSTOMER CENTRIC. We are customer-centric in all that we do
COLLABORATIVE. We are collaborative, able to work across teams and capitalise on the diversity of intellect, perspectives, and experiences.

We are committed to ensuring all candidates feel welcomed and supported. Should your application advance and you require accommodations for the interview process, please inform us so we can make the necessary arrangements.

Reward and benefits at Fastmarkets

We believe in fair pay and benefits that support you both inside and outside of work. Through Fastmarkets Rewards, you'll have access to a range of core benefits and a flexible allowance, giving you the freedom to tailor your package to suit your lifestyle, wellbeing and financial priorities. We know that everyone's needs are different, so we've designed our benefits to support our diverse global team wherever they're based.

Specific benefits may vary by country and role.

You’ve read a little about us – now it’s over to you!

If you like what you’ve read so far and think you can see yourself as a Fastmarkets person, it’s time to fill in your application form. This form is an important part of the selection process: it’s used to determine whether or not you’ll be chosen to have an interview and acts as a basis for the questions we’ll ask you on the day.

It’s vital that you try to capture all the relevant information we have asked for on the form so we can get a good feel for who you are and why you’re great.

By clicking the link above or any third-party link within this posting, you are leaving this site and going to a third-party website where the third-party website's terms and privacy policy apply"""
BODY_Z0 = """Principal Data & AI Engineer, Reporting and Insights

Company: Expedia Group
Location: San Jose, California
Employment type: Full-Time Regular
Posted: 08/31/2026
Job ID: R-107931

At Expedia Group, we help travelers explore the world, one journey at a time. As a global travel company powered by passionate people, trusted partnerships, and leading technology, we connect travelers, partners, and advertisers through our consumer brands, B2B network, and travel advertising business.




Here, you'll do meaningful work that helps millions of people discover, book, and experience travel with more ease, confidence, and joy. Our five Behaviors-Traveler First, Think Big, Operate with Excellence, Ownership Mindset, and Succeed Together-help foster a supportive environment where people can grow their careers and have the flexibility, benefits, and support to do their best work. Join us and build for travelers everywhere.

Principal Data & AI Engineer, Reporting and Insights

Introduction to the Team:

Our Technology team partners across Expedia Group to create innovative products, services, and tools that deliver high-quality experiences for travelers, partners, and employees. Our shared technology platform, powered by data and machine learning, enables secure, differentiated, and personalized experiences that build loyalty and improve traveler satisfaction.


This role sits within the Strategic Operations and Execution organization in the CTO Office and leads the AI Reporting and Insights capability, helping leaders turn complex data into clear, decision-ready insights. As the Principal Data Engineer, AI Reporting and Insights, you will define how Expedia Group transforms operational, portfolio, and performance data into trusted executive insights. You will bring together reporting strategy, data architecture, and AI-enabled delivery to improve decision-making, reduce manual work, and build a scalable reporting foundation across the organization.


You will also help set the standard for responsible, high-quality AI-powered reporting by applying large language models, agentic AI workflows, and modern AI tooling to executive reporting and self-service insights.

In this Role You Will:

Own the AI-powered reporting and insights strategy from data ingestion through executive delivery, creating a unified approach to dashboards, metrics, narratives, and self-service insight products.

Lead the Data Integrations and Enablement Platform, including the reporting data architecture, pipelines, and infrastructure needed to support trusted, scalable reporting.

Integrate business intelligence, metrics, and AI-assisted reporting into a connected capability that improves quality, speed, and usability for leaders and teams.

Set technical and operational standards within CTO Office while inheriting the EG standards for reporting tools and platforms, including Tableau, Looker, and AI-native reporting solutions.

Design and implement LLM-powered reporting workflows, including prompt engineering, retrieval-augmented generation (RAG), and agentic pipelines, to automate narrative generation, surface anomalies, and deliver self-service insight products.

Evaluate, select, and integrate enterprise approved AI platforms such as Azure OpenAI, AWS Bedrock, Anthropic, or similar solutions, ensuring reliability, security, and cost efficiency in production use cases.

Establish governance standards for executive-facing AI outputs, including hallucination mitigation, validation, accuracy monitoring, and responsible AI practices.

Partner with senior leadership on the insights roadmap, investment priorities, and capability-building decisions that shape the future-state reporting model.

Provide technical leadership and coaching across the reporting ecosystem, helping teams adopt clear standards, stronger practices, and modern ways of working.

Minimum qualifications:

Bachelor's degree in Computer Science, Information Systems, Data Science, Business Intelligence, or a related technical field; or equivalent professional experience.

10 years of experience in data, analytics, business intelligence, reporting, or related technical roles with a Masters, 12 years with a Bachelors, or equivalent professional experience.

Strong proficiency in Python and SQL for data engineering, pipeline development, analytics, and AI/ML integration.

3+ years of hands-on experience building or deploying AI/ML or LLM-based applications, including prompt engineering, RAG architectures, or agentic workflows using frameworks such as LangChain, LlamaIndex, or equivalent tools.

2+ years of experience with at least one enterprise AI platform, such as Azure OpenAI, AWS Bedrock, Google Vertex AI, or an equivalent platform.

Preferred qualifications:

5+ years of experience leading cross-functional data or analytics programs at a Principal level or equivalent scope.

Experience designing and operating agentic AI systems that generate reports, answer data questions, or monitor metrics with minimal human intervention.

Familiarity with natural language interfaces for analytics, including NL-to-SQL and conversational BI patterns for enterprise environments.

Understanding AI output governance, including evaluation frameworks, confidence scoring, escalation patterns, and risk management for executive reporting use cases.

Experience with modern data platforms such as EG specific implementations of Spark and Flink on top of Iceberg. Snowflake, Databricks, or Delta Lake.

Familiarity with real-time or event-driven data patterns for low-latency insight delivery.

Strong executive communication skills, with the ability to translate complex technical concepts into clear business outcomes.

Working knowledge of responsible AI principles, including explainability, auditability, and trust in AI-generated summaries and recommendations.

The total cash range for this position in San Jose is $249,000.00 to $348,500.00. Employees in this role have the potential to increase their pay up to $398,500.00, which is the top of the range, based on ongoing, demonstrated, and sustained performance in the role.&#xa;


Starting pay for this role will vary based on multiple factors, including location, available budget, and an individual’s knowledge, skills, and experience. Pay ranges may be modified in the future.




Benefits and perks

Expedia Group offers benefits and perks designed to support employees and their families, including medical, dental, and vision coverage, paid time off, an Employee Assistance Program, wellness and travel reimbursement, travel discounts, and International Airlines Travel Agent Network (IATAN) membership. Learn more about life at Expedia Group at https://careers.expediagroup.com/life.




Accommodation requests

Expedia Group is committed to providing an inclusive and accessible recruiting experience. If you need an accommodation or adjustment due to a disability during the application or recruiting process, please submit a request at https://expedia.service-now.com/askeg?id=job_accommodation."""

BODY_Z0 += (
    "\n\nAbout Expedia Group"
    "\n\nExpedia Group includes three flagship consumer brands - Expedia, "
    "Hotels.com, and Vrbo - along with a leading B2B travel business and travel "
    "advertising offerings. Across our brands and business, we help travelers "
    "explore the world with confidence and ease."
    "\n\nImportant notice"
    "\n\nEmployment opportunities and job offers at Expedia Group will always "
    "come from Expedia Group's Talent Acquisition and hiring teams. Never share "
    "sensitive personal information unless you are confident of the recipient. "
    "Expedia Group does not extend job offers via email or messaging tools to "
    "individuals with whom we have not made prior contact. Our email domain is "
    "@expediagroup.com. The official place to find and apply for roles is "
    "https://careers.expediagroup.com/jobs/."
    "\n\nEqual Opportunity"
    "\n\nExpedia is committed to creating an inclusive work environment with a "
)
