# Indian Regulatory Constraints and FYERS API v3 Capabilities for a Personal NSE Trading/Signal Platform (as of 11 Nov 2026)

Scope note: These notes are factual research, not legal advice. Primary sources are used where they could be retrieved (SEBI consolidated RA Regulations PDF amended up to 10 Oct 2026, the SEBI circular page, FYERS official API docs and notices). Many NSE archive PDFs timed out during research, so some NSE details come from broker and law-firm summaries. These are flagged where used.

---

## Q1. When do buy/sell calls count as regulated "research" or "investment advice", and what labels and disclaimers are required? (RA Regulations 2014, the 2024-2026 amendments, RA circulars, IA Regulations, AI disclosure)

### Takeaway
Under the SEBI (Research Analysts) Regulations, 2014, registration is triggered when a person, **for consideration** (any economic benefit, cash or non-cash, direct or indirect, "from client or otherwise"), is in the business of providing "research services". Research services expressly include "buy/sell/hold" recommendations, price or stop-loss targets, model portfolios and **"trading calls"**, provided to clients, other persons, groups or the general public. A tool that generates signals only for its owner's own trading falls outside this definition. Distributing those signals to others for any form of consideration brings it into RA territory. Registered RAs must disclose how far they use AI tools, remain solely responsible for AI output, and carry prescribed risk warnings. They may not advertise past performance, except through the PaRRVA and interim certified-performance route described in Q2.

### Cited Findings

**Regulation history (official SEBI consolidated text, "Amended upto October 10, 2026")**
- The base regulation is SEBI (Research Analysts) Regulations, 2014, No. LAD-NRO/GN/2014-15/07/1414. — [SEBI consolidated RA Regulations PDF (amended up to 10 Oct 2026)](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)
- SEBI's own amendment history lists these amendments:
  - 26 Apr 2024: (Amendment) Regulations, 2024, SEBI/LAD-NRO/GN/2024/170.
  - 19 Aug 2024: (Second Amendment) Regulations, 2024, SEBI/LAD-NRO/GN/2024/199.
  - **16 Dec 2024: (Third Amendment) Regulations, 2024, SEBI/LAD-NRO/GN/2024/220.** This is the main overhaul, footnoted "w.e.f. 16-12-2024".
  - 6 Aug 2025: (Amendment) Regulations, 2025, SEBI/LAD-NRO/GN/2025/252.
  - 25 Nov 2025: (Second Amendment) Regulations, 2025, SEBI/LAD-NRO/GN/2025/277, w.e.f. 25-11-2025.
  - 10 Oct 2026: (Amendment) Regulations, 2026, SEBI/LAD-NRO/GN/2026/321. Its footnotes read "w.e.f. 09-11-2026".
  - Source for all of the above: [SEBI consolidated RA Regulations PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)
- **Naming conflict:** some secondary sources call the 16 Dec 2024 amendment the "Second Amendment". SEBI's own consolidated text calls it the **Third** Amendment. — [TaxGuru](https://taxguru.in/sebi/sebi-research-analysts-third-amendment-regulations-2024.html) vs [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)
- The 2026 amendment (w.e.f. 09-11-2026) is minor:
  - It inserts a definition of "institutional investor" (Reg 2(1)(ia)), borrowed from the ICDR Regulations 2018.
  - It drops the call-recording requirement for communications with institutional-investor clients (Reg 25(1)(vii) proviso).
  - Source: [SEBI consolidated RA Regulations PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)

**Who must register (Reg 2 definitions and Reg 3)**
- Reg 2(1)(u), as substituted w.e.f. 16-12-2024: "'research analyst' means a person who, **for consideration**, is engaged in the business of providing research services and includes a part-time research analyst." — [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)
- Reg 2(1)(fa): "'consideration' means any form of economic benefit including non-cash benefit, received or receivable, directly or indirectly, in any form whether from client or otherwise for providing research services". — [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)
- Reg 2(1)(wa) defines "research services" as:
  - (i) preparing or publishing a research report or its content;
  - (ii) providing research report or analysis;
  - (iii) making 'buy/sell/hold' recommendations;
  - (iv) giving a price target or stop loss target;
  - (v) opinion on a public offer;
  - (vi) recommending a model portfolio;
  - **(vii) providing trading calls;**
  - (viii) "any other service of similar nature or character".
  - These cover listed or to-be-listed securities, "whether or not any such person has the job title of 'research analyst' to the clients or other persons or group of persons or general public." — [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)
- Reg 2(1)(zc): "'trading calls' means intraday, ultra-short duration, non-delivery based (other than hedging) recommendation or any recommendation related to securities that are not personalized or investor specific." — [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)
- Reg 2(1)(nd): "part-time research analyst" is an individual or partnership firm that provides research services for consideration and also has another business activity or employment. A developer with a day job can therefore register as a part-time RA. — [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)
- Reg 2(1)(w) excludes these from a "research report":
  - comments on general market trends;
  - discussions on broad-based indices;
  - economic, political or market commentaries;
  - internal communications not given to current or prospective clients;
  - statistical summaries of company financial data;
  - "technical analysis relating to the demand and supply in a sector or the index".
  - Source: [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)
- Reg 3(1): "no person shall act as a research analyst or research entity or hold itself out as a research analyst unless he has obtained a certificate of registration from the Board". — [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)
- The only statutory exemptions (Reg 3 provisos) are:
  - investment advisers, credit rating agencies, AMCs and fund managers (subject to Chapter III);
  - principal officers, associated persons and partners of a registered RA.
  - There is **no express "personal use" exemption**, because personal use never meets the definition in the first place.
  - Source: [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)
- A law-firm commentary on the 2024 amendments says individuals can offer research without registering "provided that these services are offered without any direct or indirect consideration". — [Mondaq](https://www.mondaq.com/india/securities/1574012/navigating-the-updated-regulatory-framework-for-investment-advisers-and-research-analysts)
- Reg 4: anyone located outside India who issues research on Indian-listed securities must enter into an agreement with a registered RA or research entity. — [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)

**Qualifications and deposit**
- Qualification (Reg 7(1)), as substituted w.e.f. 25-11-2025: either (a) a graduate degree in any discipline, or a CFA Charter, plus relevant NISM certification; or (b) NISM's Post Graduate Program in the Securities Market (Research Analysis).
- Re-certification is required before the existing certificate expires, or within 3 years of registration.
- Source: [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)
- Net worth was replaced by a bank deposit of INR 1 lakh to INR 10 lakh, depending on client count. The deposit is lien-marked in favour of RAASB (BSE). — [AZB & Partners](https://www.azbpartners.com/bank/overhaul-of-the-regulatory-framework-for-investment-advisers-and-research-analysts/); Reg 8 in the [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)

**AI-tool rules**
- Reg 19(vii), inserted w.e.f. 16-12-2024: "A research analyst or research entity shall disclose to the client the extent of use of Artificial Intelligence tools in providing research services." — [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)
- Reg 24(7): an RA "who uses Artificial Intelligence tools, irrespective of the scale and scenario of adoption of such tools, for servicing its clients shall be solely responsible for the security, confidentiality and integrity of the client data, use of any other information or data for research services, research services based on output of Artificial Intelligence tools and compliance with any law". — [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf); regulation numbering per [TaxGuru](https://taxguru.in/sebi/sebi-research-analysts-third-amendment-regulations-2024.html)
- Reg 24(8): model-portfolio RAs must follow SEBI guidelines. — [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)
- Existing clients had to be compliant with the AI disclosure and terms-and-conditions requirements by 30 Apr 2025. — [AZB & Partners](https://www.azbpartners.com/bank/overhaul-of-the-regulatory-framework-for-investment-advisers-and-research-analysts/)

**Circulars**
- **Guidelines for RAs circular:** SEBI/HO/MIRSD/MIRSD-PoD-1/P/CIR/2025/004 dated 8 Jan 2025. — [Legality Simplified / search summary](https://www.legalitysimplified.com/sebi-master-circular-on-research-analysts/); [Scribd copy](https://www.scribd.com/document/821467090/SEBI-issued-the-Guidelines-for-Research-Analysts-RA-Jan082025)
  - Note: the Dec 2024/Jan 2025 item is a *guidelines* circular. The consolidated *master* circulars are:
    - SEBI/HO/MIRSD/MIRSD-PoD-1/P/CIR/2024/49 dated 21 May 2024;
    - SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/95 dated **27 Jun 2025**, covering circulars up to 20 Jun 2025.
    - Source: [Lexibox (text of 2025 master circular)](https://www.lexibox.in/ra/master-circular-for-research-analysts-2025/); [SEBI 2024 master circular PDF](https://www.sebi.gov.in/sebi_data/attachdocs/may-2024/1716290553655.pdf)
- A secondary blog claims a newer RA master circular dated 6 Feb 2026. **Unverified.** — search summary citing [Alphaquark](https://alphaquark.in/blog/social-media-guidelines-sebi-registered-advisors)
- The 2025 master circular, para 1.7, repeats the AI-use disclosure. It also requires the disclosure in the terms and conditions. — [Lexibox](https://www.lexibox.in/ra/master-circular-for-research-analysts-2025/)

**Required labels and disclaimers (Advertisement Code, Clause 11 of the 2025 RA master circular)**
- Standard warning, 11.1(b)(iii): "Investment in securities market are subject to market risks. Read all the related documents carefully before investing." — [Lexibox](https://www.lexibox.in/ra/master-circular-for-research-analysts-2025/)
- Registration disclaimer: "Registration granted by SEBI, enlistment with BSE and certification from NISM in no way guarantee performance of the intermediary or provide any assurance of returns to investors." — [Lexibox](https://www.lexibox.in/ra/master-circular-for-research-analysts-2025/)
- Prohibited:
  - "Reference to past performance of the RA" (11.1(c)(xii));
  - promises of "assured or risk free return" (11.1(c)(x));
  - superlatives such as "Best", "No. 1", "Top Research Analyst".
  - The code covers social media and messaging platforms.
  - Source: [Lexibox](https://www.lexibox.in/ra/master-circular-for-research-analysts-2025/)
- Disclaimers for activities outside SEBI's purview must be in at least 10-point font. — search summary of the 2025 master circular ([Lexibox](https://www.lexibox.in/ra/master-circular-for-research-analysts-2025/))

**Fees and client terms**
- Individual/HUF clients: maximum Rs 1,51,000 per annum per family, excluding statutory charges.
- Advance fees may not exceed 1 year (para 1.9(f)). Annexure B says "presently it is one quarter", so the circular is internally inconsistent.
- Pro-rata refund on termination, with no breakage fee.
- Source: [Lexibox](https://www.lexibox.in/ra/master-circular-for-research-analysts-2025/); [AZB](https://www.azbpartners.com/bank/overhaul-of-the-regulatory-framework-for-investment-advisers-and-research-analysts/)
- RAs must:
  - maintain a functional website (Reg 19A);
  - keep KYC of fee-paying clients;
  - keep records of every recommendation and its rationale for 5 years (Reg 25);
  - get an annual compliance audit.
  - Source: [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)
- RAs must not trade in recommended securities from 30 days before to 5 days after a report, nor trade against their own recommendation (Reg 16(2)-(3)). This matters if the platform owner both trades and publishes signals. — [SEBI consolidated PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)

**Investment Advisers (IA) Regulations, 2013, Dec 2024 amendment**
- Investment advice now covers only securities within SEBI's purview.
- **IAs cannot provide "trading calls"**, so signal services sit under the RA regime, not the IA regime.
- The fixed-fee cap is INR 1.51 lakh per annum.
- The same AI-responsibility and disclosure principle applies.
- Source: [AZB & Partners](https://www.azbpartners.com/bank/overhaul-of-the-regulatory-framework-for-investment-advisers-and-research-analysts/)

### Inferences
- A signal engine that only feeds its owner's own orders is not "research services", because nothing is provided to "clients or other persons ... or general public" for consideration. No RA registration is needed for that use.
- Opening the platform to others changes this. Even "free" signals may meet the "consideration" test if the operator gets any indirect economic benefit, such as ads, referral or brokerage revenue-share, data monetisation, or upsell to a paid tier. The definition expressly includes non-cash and indirect benefits "from client or otherwise".
- Automated or AI-generated buy/sell output shown to other users would fall under "trading calls", "buy/sell/hold recommendation" or "any other service of similar nature". RA rules contain no tools or software exemption.
- Index-level commentary and pure technical analysis of index or sector supply/demand fall within the Reg 2(1)(w) exclusions. Stock-specific signals do not.

### Gaps
- I did not retrieve the full text of the 8 Jan 2025 RA guidelines circular, so I could not confirm whether it contains specific provisions on algorithm- or app-generated research. No source found addresses "tools/software that generate recommendations" specifically. The rules are technology-neutral.
- I could not confirm whether a Feb 2026 RA master circular exists. The latest confirmed one is SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/95 of 27 Jun 2025.
- The IA Regulations' exact current definition text was not fetched. The IA points above rely on the AZB summary.

---

## Q2. Finfluencer restrictions, past-performance claims and the live-market-data ban for "education"

### Takeaway
Since Aug 2024, SEBI-regulated entities, brokers included, may not associate with unregistered persons who give securities advice or make return claims. Brokers had to cut such ties by about 21 Jan 2025. Past-performance claims are banned in advertising. RAs and IAs may share CA-certified performance only on a client's specific request (interim route, 30 Oct 2025 circular) until PaRRVA-verified metrics become mandatory. Educators may not use live prices. The Jan 2025 three-month lag was relaxed to a uniform **30-day lag from 1 Jul 2026** (circular of 8 May 2026). In Aug 2026 SEBI publicly warned against "live trading strategy" sessions.

### Cited Findings

**Association with unregistered persons**
- SEBI (Intermediaries) (Amendment) Regulations, 2024: notified 26 Aug 2024, Gazette 29 Aug 2024.
  - Reg 16A bars regulated persons from associating with persons who give unregistered advice or make unapproved return/performance claims.
  - Reg 16B gives SEBI enforcement powers.
  - Sources disagree on the effective date (26 Aug vs 29 Aug 2024).
  - Source: [Taxmann](https://www.taxmann.com/post/blog/sebi-amends-intermediaries-regulations-bars-intermediaries-from-associating-with-unregistered-security-advisors); [search summary incl. TaxGuru/SCC](https://www.scconline.com/blog/?p=329857)
- Implementing circular: SEBI/HO/MIRSD/MIRSD-PoD-1/P/CIR/2024/143 dated 22 Oct 2024. Regulated entities had to end existing associations within 3 months. — [Khaitan & Co copy of 22 Oct 2024 circular](https://www.khaitanco.com/sites/default/files/2026-03/SEBI%20Circular%20dated%2022%20October%202024%20on%20Association%20of%20persons%20regulated%20by%20the%20Board%20and%20their%20agents%20with%20certain%20persons.pdf); [Outlook Business](https://www.outlookbusiness.com/markets/sebi-directs-regulated-entities-to-sever-ties-with-finfluencers-in-3-months)
- The RA master circular (Clause 20) carries this forward. Contracts had to be terminated by 21 Jan 2025. Investor education and association through a "specified digital platform" are carved out. — [Lexibox](https://www.lexibox.in/ra/master-circular-for-research-analysts-2025/)

**Clarification and the live-data ban for education**
- Clarification circular: SEBI/HO/MIRSD/MIRSD-PoD-1/P/CIR/2025/11 dated 29 Jan 2025. — [KS&K](https://ksandk.com/newsletter/sebi-unregistered-investment-claim-makers/)
- Under it, educators could use only market price data with at least a 3-month lag (FAQ Q8). — [Business Standard](https://www.business-standard.com/markets/news/sebi-finfluencer-circular-live-stock-data-market-education-rules-125013000571_1.html); [Taxscan](https://www.taxscan.in/finfluencers-beware-sebi-cracks-down-on-live-market-data-usage/485232)
- Dec 2025: SEBI Chairman Tuhin Kanta Pandey acknowledged "inconsistencies between two SEBI circulars on the use of live data". — [Business Standard, Dec 2025](https://www.business-standard.com/amp/markets/capital-market-news/sebi-to-bar-use-of-live-market-data-in-investor-education-125120900643_1.html)
- **Current rule:** Circular HO/47/17/12(11)2025-MRD-POD3/I/11107/2026 dated **8 May 2026**, "Norms for sharing and usage of price data for educational purposes", effective **1 Jul 2026**.
  - It sets a uniform **30-day lag** for both sharing (by MIIs and intermediaries) and usage of price data for investor education.
  - Conditions: no monetary incentive to participants, and a formal agreement with an audit trail.
  - NISM gets a 1-day-lag carve-out for its simulation lab only.
  - It modifies paras 2(iii)-(iv) of the 24 May 2024 MII circular SEBI/HO/MRD/MRD-PoD3/P/CIR/2024/56 (sharing lag changes from 1 day to 30 days) and FAQ Q8 of the 29 Jan 2025 circular (usage lag changes from 3 months to 30 days).
  - Source: [CorpLaw Updates](https://www.corplawupdates.in/updates/sebi-30-day-lag-educational-price-data-norms-2026); [LiveLaw Biz](https://www.livelawbiz.com/amp/securities-law/sebi/securities-and-exchange-board-of-india-revises-norms-sharing-and-usage-market-price-data-educational-purposes-533509)
- 17 Aug 2026, SEBI PR No. 48/2026: cautioned investors against finfluencers running "live trading strategy" sessions using real-time data. It stated that live market data may be shared only for orderly functioning of the market or regulatory requirements. — [Medianama](https://www.medianama.com/2026/08/223-sebi-influencers-trading-strategies/); [CorpLaw Updates](https://www.corplawupdates.in/updates/sebi-caution-live-trading-strategies-social-media-2026)

**Past performance and PaRRVA**
- The advertisement code prohibits reference to the RA's past performance. — [Lexibox](https://www.lexibox.in/ra/master-circular-for-research-analysts-2025/)
- SEBI circular of 30 Oct 2025, "Ease of doing business – interim arrangement for certified past performance":
  - RAs and IAs may share past performance **only on specific request** from a client or prospect, not on websites, social media or marketing.
  - It must be certified by an ICAI/ICMAI member, use a consistent methodology, and carry a disclaimer that it is not PaRRVA-verified and that past performance does not guarantee future results.
  - Once PaRRVA is operational, entities have 3 months to enrol. Two years after operationalisation, only PaRRVA-verified metrics may be shown.
  - The circular number was not confirmed (SEBI URL slug ends _97556).
  - Source: [CS Kruti](https://cskruti.com/sebi-allows-ias-ras-to-share-past-performance/)
- PaRRVA (Past Risk and Return Verification Agency):
  - Framework issued April 2025. — [Business Standard, 4 Apr 2025](https://www.business-standard.com/markets/news/market-regulator-sebi-issues-framework-for-return-verification-agency-125040401110_1.html)
  - Pilot launched early Dec 2025 by CARE Ratings with NSE as data centre. First phase covers IAs, RAs and **stock brokers providing algorithmic trading services**. — [Business Standard, Dec 2025](https://www.business-standard.com/amp/markets/news/sebi-launches-return-verification-framework-parrva-to-curb-fake-performance-claims-125120800842_1.html)
  - Secondary blogs say it went fully live around 4 May 2026, with an enrolment deadline of 3 Sep 2026. **Unverified.** — [Univest blog](https://univest.in/blogs/parrva-sebi-past-risk-and-return-verification-agency-explained)

### Inferences
- A multi-user platform that shows live NSE prices next to buy/sell calls, or "live strategy" streams, is directly in the zone SEBI flagged in Aug 2026.
- Educational or backtest content shown to others should use data at least 30 days old (from 1 Jul 2026), unless the platform is a registered RA providing research to its clients.
- Any marketing of signal performance must avoid return claims. If the operator is a registered RA, those claims must go through PaRRVA or the interim certified-on-request route.

### Gaps
- I did not retrieve the 8 May 2026 circular's text from sebi.gov.in directly. The details come from CorpLaw Updates and LiveLaw Biz.
- I could not confirm the circular number of the 30 Oct 2025 past-performance circular.
- I could not confirm from a primary source the exact PaRRVA operational date in 2026.

---

## Q3. SEBI retail algo trading framework and timelines

### Takeaway
SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 (4 Feb 2025) set up the framework. Its key features:
- the broker is principal and the algo provider is the broker's agent;
- every API order carries an exchange algo ID;
- no open APIs: a vendor-client-specific API key plus a broker-whitelisted static IP, OAuth only, and 2FA;
- algo providers are empanelled by exchanges;
- black-box providers must register as RAs;
- self-built retail algos need registration only above an orders-per-second threshold.

The start date moved from 1 Aug 2025 to 1 Oct 2025, then to a glide path, with full applicability to all brokers from **1 Apr 2026**.

### Cited Findings

**The 4 Feb 2025 circular**
- Circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 dated 4 Feb 2025, "Safer participation of retail investors in Algorithmic trading". — [SEBI](https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html)
- Key provisions, per a summary of the circular text:
  - Para I(a): brokers act as principal; algo providers and fintech vendors act as the broker's agent.
  - Para I(b): API orders must carry a unique exchange-issued identifier.
  - Para I(c): self-developed algos by "tech-savvy retail investors" need exchange registration through the broker **only if they exceed the specified order-per-second threshold**. A registered algo may be used by the investor's **family (self, spouse, dependent children, dependent parents) but not other investors**.
  - Note 2: the threshold is set by the Brokers' Industry Standards Forum with the exchanges, in consultation with SEBI.
  - Para I(d): **no open APIs**. Access only via a unique vendor-client-specific API key and a broker-whitelisted static IP. OAuth-based authentication only, with 2FA for API access. Brokers may deal only with empanelled algo providers.
  - Para II: broker needs exchange permission for each algo, and for any modification.
  - Para III: algo providers are not SEBI-regulated but must be exchange-empanelled. Brokers do due diligence. Fee and brokerage sharing is allowed with full disclosure.
  - Para IV: exchanges hold a kill switch per algo ID.
  - Para V: **white box (execution) algos** have disclosed, replicable logic. **Black box algos** have logic unknown to the user and not replicable. **Black-box providers must register as Research Analysts**, maintain a detailed research report per algo, and re-register on any logic change.
  - Para 7: implementation standards were due by 1 Apr 2025; applicability from 1 Aug 2025.
  - Source: [TaxGuru (circular text)](https://taxguru.in/sebi/sebi-circular-safer-participation-retail-investors-algorithmic-trading.html)

**Extensions**
- Circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/108 dated 29 Jul 2025 postponed the effective date to 1 Oct 2025. — [search summary (TaxGuru/Taxmann)](https://taxguru.in/?p=977588); [Angel One](https://www.angelone.in/news/market-updates/sebi-pushes-algo-trading-deadline-to-october-1-2025)
- Circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/132 dated 30 Sep 2025 set the glide path:
  - brokers could go live from 1 Oct 2025;
  - 31 Oct 2025: apply to register retail algo products and at least one strategy;
  - 30 Nov 2025: registration complete;
  - 3 Jan 2026: participate in at least one mock session;
  - from **5 Jan 2026**, non-compliant brokers are barred from onboarding new retail API-algo clients;
  - **full framework applicable to all brokers from 1 Apr 2026.**
  - Source: [TaxGuru](https://taxguru.in/sebi/sebi-extends-algo-trading-implementation-timeline-april-2026.html); [Upstox](https://upstox.com/news/market-news/financial-regulations/sebi-extends-timeline-for-retail-algo-trading-framework-sets-glide-path-for-brokers/article-182285/)
- BSE issued a 24 Nov 2025 notice on "adherence to milestones" of the glide path. — [BSE circular mirror](https://rhnvrm.github.io/stock-market-circulars/circulars/bse/2025/bse-2025-11-24-e6eac9e12bd239db-adherence-to-milestones-and-the-rules-related-to-retail-algo/)
- FYERS confirms the new framework took effect 1 Apr 2026, with old and new frameworks running in parallel until 31 Mar 2026. — [FYERS notice, 10 Mar 2026](https://fyers.in/notice-board/new-sebi-framework-for-retail-algo-trading-from-april-01-2026)

### Inferences
- As of Nov 2026 the framework is fully in force. No SEBI phase after Apr 2026 was found.

### Gaps
- I found no evidence of a further SEBI phase or a revised OPS threshold after 1 Apr 2026. The searches surfaced none, but an exhaustive check of NSE circulars was not possible because nsearchives.nseindia.com timed out.

---

## Q4. NSE implementation standards: OPS threshold, algo ID, white/black box, empanelment, static IP, API keys, self-developed algos, daily login/2FA

### Takeaway
NSE circular NSE/INVG/67858 (5 May 2025) sets the details:
- **10 orders per second per exchange per segment** is the threshold (exchanges can adjust it after market notice);
- below it, client algos need no registration and carry a **generic algo ID**;
- above it, client algos must be registered through the broker for a unique ID;
- one static IP maps to one client (family sharing allowed per NSE summaries);
- IP changes are allowed weekly;
- all API sessions must be **logged out daily**.

Operational modalities (NSE/INVG/69255, 22 Jul 2025, with corrigendum NSE/INVG/70309 of 19 Sep 2025) govern empanelment and strategy registration. As implemented by brokers from 1 Apr 2026, users complete **2FA once each trading day**, and refresh-token sessions are gone.

### Cited Findings

**NSE/INVG/67858 (5 May 2025)**
- It sets a tiered regime: up to 10 OPS uses a generic algo ID with no registration; above 10 OPS needs registration with each exchange and a unique ID. — [search summary incl. Business Standard](https://www.business-standard.com/markets/capital-market-news/nse-lays-down-new-ground-rules-for-retail-algo-trading-to-boost-safety-and-compliance-125050600690_1.html); [Nithin Kamath on X](https://x.com/Nithin0dha/status/1919687724027551901)
- Threshold wording: "Initially set at a maximum of 10 orders per second per exchange or segment". It may be adjusted by exchanges after market notice. NSE calls it TOPS (Threshold Order Per Second). — [Groww](https://groww.in/blog/nse-issues-new-compliance-norms-for-retail-algo-trading)
- Static IP and API keys, per Groww:
  - "a single static IP can be mapped to only one client at a time"; family sharing is permitted;
  - "Clients will have the ability to update their mapped static IP addresses on a weekly basis";
  - "Clients may be issued multiple API keys", but non-registered algos must route through one designated key;
  - "All API sessions must be logged out daily."
  - Source: [Groww](https://groww.in/blog/nse-issues-new-compliance-norms-for-retail-algo-trading)
- Zerodha's reading:
  - limits are "per API key";
  - only one API key per user may run an unregistered algo at 10 OPS or below;
  - a static IP is "required only for order placement";
  - "family members can share static IPs";
  - a backup IP is needed;
  - IPv6 is allowed and the IP need not be in India;
  - OAuth/2FA and "no open APIs" apply to all algo types.
  - Source: [Zerodha Z-Connect](https://zerodha.com/z-connect/general/a-comprehensive-overview-of-nses-circular-on-the-new-retail-algo-trading-framework)
- **Conflict:** FYERS forum and support guidance says "Shared IPs are not allowed. Each IP address must be unique across all users." This is stricter than the family-sharing reading of NSE's standard. — [FYERS community blog](https://fyers.in/community/blogs-gdppin8d/post/sebi-s-new-algo-trading-rules-kick-in-on-april-1-here-is-what-changes-Yew3vdG4CgoXk1q) vs [Groww](https://groww.in/blog/nse-issues-new-compliance-norms-for-retail-algo-trading) and [Zerodha](https://zerodha.com/z-connect/general/a-comprehensive-overview-of-nses-circular-on-the-new-retail-algo-trading-framework)

**Operational modalities and empanelment**
- NSE/INVG/69255 dated 22 Jul 2025, "Operational modalities for empanelment of Algo Providers and registration of retail algo strategy":
  - empanelment applications go through trading members, with turnaround of about T+30 working days;
  - algo registration takes about T+10 working days;
  - in-house broker algos need no provider empanelment.
  - Source: [Business Standard](https://www.business-standard.com/markets/news/nse-unveils-guidelines-for-retail-algo-trading-effective-august-1-125072301458_1.html); [X post citing circular](https://x.com/algotradingdesk/status/1949680634840105411)
- Corrigendum NSE/INVG/70309 dated 19 Sep 2025 covers:
  - an expanded definition of "Client Direct API";
  - ISO 27001:2022;
  - half-yearly VAPT audits;
  - liability clarity.
  - Source: [search summary](https://alphaquark.in/blog/sebi-retail-algo-trading-rules-2026-guide)
- NSE text on black-box algos: "In all cases where there is a Black Box Algo, the ALGO provider needs to be registered as RA with SEBI."
  - NSE FAQ (3 Nov 2025): an RA wanting to deploy a black-box algo must first become an empanelled algo provider.
  - Because algos must be hosted on the broker's server, one provider cannot host black-box algos for several third-party RAs.
  - Source: [search summary of NSE FAQ](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/FAQ_Retail%20Algo_03112025_NSE.pdf). Direct fetch timed out, so this is secondary.
- NSE circular dated 22 Sep 2026 (PDF INVG76481), "Final Empanelment of Algo Providers Currently Empanelled on a Provisional Basis", lists:
  - AlgoBulls Technologies;
  - Quantiply Technologies;
  - Simply Algo Fintech;
  - Stratzy Fintech;
  - Modern Algos;
  - "Includes vendors providing whitebox and/or blackbox algorithmic trading solutions."
  - Source: [exchangecirculars.com mirror](https://exchangecirculars.com/circulars/nse/2026/nse-2026-09-22-450491def5758600-final-empanelment-of-algo-providers-currently-empanelled-on-a-provisional-basis-/)

**Daily login / 2FA (as implemented)**
- FYERS (from 1 Apr 2026):
  - orders accepted only from a registered App ID mapped to a whitelisted static IP;
  - "Users must complete 2FA once per trading day. Continuous refresh-token sessions are no longer supported";
  - max 10 orders per second;
  - market orders auto-converted to MPP (Market Price Protection) orders;
  - third-party platforms must be "empanelled and hosted within the broker's infrastructure".
  - Source: [FYERS notice, 10 Mar 2026](https://fyers.in/notice-board/new-sebi-framework-for-retail-algo-trading-from-april-01-2026)
- 5paisa's coverage frames these as mandatory 2FA and audit trails from 1 Apr. — [5paisa](https://www.5paisa.com/news/sebi-tightens-algo-trading-rules-with-mandatory-2fa-and-audit-trails-from-april-1)

### Inferences
- **Yes, the daily login/2FA requirement started on 1 Apr 2026** for FYERS users. It traces to the "logged out daily" clause in NSE's standards and SEBI's OAuth/2FA mandate.
- A personal platform must build a once-per-day interactive 2FA step, such as a morning login. Fully unattended token refresh is no longer possible.

### Gaps
- I could not read NSE/INVG/67858, NSE/INVG/69255 or the NSE FAQ PDFs directly (nsearchives timeouts). The following are unconfirmed from primary text:
  - the exact count of static IPs (primary plus backup);
  - provider empanelment criteria such as net worth or fees;
  - whether the "daily logout" clause specifies a time.

---

## Q5. Placing orders automatically for one's own account vs offering algos/signals to others

### Takeaway
Automating one's **own** FYERS account through the API is permitted, and FYERS treats it as algo trading. It needs a registered App ID on a whitelisted static IP, daily 2FA, and at most 10 OPS. Exchange registration is needed only above 10 OPS. Running algos or signals for **other people** is a different category:
- algos must be offered via a broker, registered per strategy with the exchange, and supplied by an exchange-empanelled provider hosted on broker infrastructure;
- black-box strategies require SEBI RA registration;
- selling buy/sell signals (trading calls) for any consideration requires RA registration;
- a self-developed registered algo may be shared only with family (self, spouse, dependent children, dependent parents).

### Cited Findings
- FYERS support: API order placement counts as algo trading, including personal setups.
  - "If the order count is less than 10 OPS, registration is not required"; only a static IP is needed.
  - "For greater than 10 OPS, algo registration is required with each exchange."
  - The 10 OPS limit covers placement, stop loss, targets and modifications.
  - Source: [FYERS community blog](https://fyers.in/community/blogs-gdppin8d/post/sebi-s-new-algo-trading-rules-kick-in-on-april-1-here-is-what-changes-Yew3vdG4CgoXk1q)
- Family-only use of a registered self-developed algo is in SEBI circular 4 Feb 2025, Para I(c). — [TaxGuru](https://taxguru.in/sebi/sebi-circular-safer-participation-retail-investors-algorithmic-trading.html)
- FYERS Individual vs Third-party apps: "Individual apps are for your own account. Third-party apps are for platforms where other FYERS clients log in with their own credentials." — [FYERS API docs, Authentication](https://fyers.in/api-docs/v3/api/authentication/)
- Third-party platforms "can only place orders if they are empanelled and hosted within the broker's own systems". Orders from InstaOptions or any API bridge are blocked. — [FYERS community blog](https://fyers.in/community/blogs-gdppin8d/post/sebi-s-new-algo-trading-rules-kick-in-on-april-1-here-is-what-changes-Yew3vdG4CgoXk1q)
- FYERS API Bridge: subscriptions discontinued 5 Mar 2026; no order placement from 1 Apr 2026. — [FYERS notice, 5 Mar 2026](https://fyers.in/notice-board/api-bridge-subscription-discontinuation-order-placement-changes/)
- Black-box providers must hold RA registration (SEBI 4 Feb 2025, Para V). Fee sharing between provider and broker is allowed with disclosure (Para III(d)). — [TaxGuru](https://taxguru.in/sebi/sebi-circular-safer-participation-retail-investors-algorithmic-trading.html)
- Selling "trading calls" for consideration is an RA research service (Reg 2(1)(wa)(vii), 2(1)(zc)). — [SEBI consolidated RA Regulations](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792127227860.pdf)

### Inferences
- A multi-user "Quant Desk"-type product that places orders in other users' accounts, even with their own FYERS logins, would need to be an empanelled algo provider hosted on the broker's infrastructure, with each strategy registered. A self-hosted third-party app making order calls for others does not fit the post-1 Apr 2026 model.
- Showing signals without auto-execution still triggers the RA regime if there is any consideration.

### Gaps
- I found no public FYERS documentation of the process for an individual to register a self-developed algo above 10 OPS.

---

## Q6. Exchange data rules: showing real-time NSE data to other users; delayed data

### Takeaway
Real-time NSE data reaches a broker's clients under the broker's NSE membership. Redistributing it to other users on a website or app needs a licence from NSE Data & Analytics, which is expensive. NSE's policy says data shall not be provided to virtual trading, simulation or gaming platforms. 15-minute delayed data is cheaper but still licensed. Separately, SEBI restricts MIIs and intermediaries from sharing real-time price data with third parties (circular of 24 May 2024) and allows education use only with a 30-day lag from 1 Jul 2026.

### Cited Findings
- NSE Data Sharing & Usage Policy: trading members and subscribers may not redistribute market data beyond what their agreement allows. Redistribution requires agreements. — [NSE Data Policy page (search summary; direct fetch timed out)](https://www.nseindia.com/static/market-data/nse-data-policy)
- Secondary summary of the NSE price list effective 1 Apr 2026 (fees exclude taxes):
  - real-time snapshot on an open website or app: ₹29,20,000 a year per website or medium;
  - 1-minute snapshot: ₹16,00,000 a year;
  - 5-minute snapshot: ₹4,20,000 a year;
  - 1-minute snapshot delayed 15 minutes: ₹1,20,000 a year;
  - end of day: ₹1,00,000 a year;
  - charting application: ₹25,50,000 a year plus ₹875 per user per month.
  - Source: [OneTradeJournal (checked 13 Oct 2026)](https://onetradejournal.com/platforms/why-market-data-is-delayed). **Not verified against NSE's own 2026 price list.**
- The same source cites NSE Data Usage and Data Sharing Policy clauses:
  - clause 4.1: brokers receive live feed data "as a part of their ongoing membership";
  - clause 7.4: NSE data "shall not be provided" to online gaming, virtual trading, simulation or fantasy platforms.
  - Source: [OneTradeJournal](https://onetradejournal.com/platforms/why-market-data-is-delayed)
- NSE's 15-minute delayed data tariff:
  - Capital Market display: about 90,000 INR domestic per display medium, with website and app counted separately;
  - real-time vendors may show delayed data on their own terminals without additional display fees;
  - delayed data passed as feeds to clients needs NSE Data & Analytics' written consent.
  - Source: [NSE 15-min delayed data tariff PDF (search summary)](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Download%2015%20mins%20delayed%20data%20tariff.pdf)
- SEBI circular SEBI/HO/MRD/MRD-PoD3/P/CIR/2024/56 (24 May 2024) governs MIIs' sharing of real-time price data with third parties. Its paras 2(iii)-(iv) were modified on 8 May 2026 to allow sharing for education only with a 30-day lag. — [CorpLaw Updates](https://www.corplawupdates.in/updates/sebi-30-day-lag-educational-price-data-norms-2026)
- A Nov 2024 SEBI advisory reportedly warned against unauthorised virtual, paper-trading and fantasy platforms using real stock prices. Many apps moved to delayed data afterwards. — [Multibagg (secondary)](https://www.multibagg.ai/market-pulse/articles/paper-trading-live-data-rules-cmud4c3t200072spfhp0855ry)

### Inferences
- Live FYERS WebSocket data used inside one's own account for one's own trading is within the broker's licence.
- Re-broadcasting the same feed to other users of a separate platform is very likely redistribution needing an NSE Data & Analytics licence. This also applies to paper-trading or simulation features, where clause 7.4 may bar provision entirely.

### Gaps
- I could not open NSE's own data policy page or the 2026 price list (timeouts). The fee figures are from a secondary site and should be confirmed with NSE Data & Analytics.
- I found no source on whether FYERS' API terms themselves prohibit redistributing API data. This should be checked in the FYERS API terms.

---

## Q7. FYERS API v3: what it can and cannot do

### Takeaway
FYERS API v3 is **free**, with a free Standard tier and a paid **Prime** subscription (₹499/month or ₹4,990/year + GST) that raises data limits sharply.
- Order placement: limit, market (MPP), SL-M (MPP) and SL-L orders; CNC, INTRADAY, MARGIN and MTF products; slicing; GTT single and OCO; "smart" orders; webhooks.
- Bracket and cover orders appear to have been **replaced** by Smart Stop-loss/Target. The API reportedly rejects productType "BO".
- WebSockets: a Data socket with 5-level depth and a TBT socket with 50-level depth for NSE equity and NFO.
- Order rate is capped at 10 orders per second. Access tokens expire daily at 6:30 AM. A static IP is needed only for order APIs.
- No FYERS strategy marketplace was found. FYERS steers automation users to its in-house **FYERS Automate**.

### Cited Findings

**Plans and costs**
- The Trading API is free. — [FYERS API product page](https://fyers.in/products/api)
- Prime costs ₹499 + 18% GST per month or ₹4,990 + 18% GST per year. It cuts brokerage to ₹15 per executed order (Standard: ₹20) and offers MTF at 12.49% p.a. — [FYERS Prime page / community (search summary)](https://fyers.in/prime); [FYERS on X](https://x.com/fyers1/status/2085314964047499423/photo/1)
- One user reports Prime was waitlisted for new users and that Data API limits were reduced. Single forum post. — [FYERS community](https://fyers.in/community/t/revised-api-rate-limits-are-too-strict/24678)

**Rate limits (official Plans and Limits page, "Last updated on October 14, 2026")**

| API category | Standard | Prime |
|---|---|---|
| Data APIs | 5/sec, 50/min, 5,000/day | 10/sec, 500/min, 5,00,000/day |
| Transaction + User Info APIs | 10/sec, 200/min, 1,00,000/day | 10/sec, 500/min, 5,00,000/day |

- Breaches return HTTP 429 (error -429). Exceeding the per-minute limit more than 3 times a day blocks the user for the rest of the day.
- Quotes API: 50 symbols per request (Standard) vs 1,000 (Prime).
- Source: [FYERS Plans & Limits](https://fyers.in/api-docs/v3/getting-started/plans-and-limits/)
- Placing, modifying and cancelling orders together must stay within **10 orders per second**. 429 responses carry `Retry-After` and `X-Retry-After-Ms` headers. — [FYERS single-order docs](https://fyers.in/api-docs/v3/api/trading/order-placement/sync/single-order/)
- Older docs and GitHub material show a flat 10/s, 200/min, 1 lakh/day for all calls. This is superseded for Data APIs by the plan split. — [FyersDev GitHub](https://github.com/FyersDev/fyers-skills/blob/master/skills/fyers-trading/references/rate-limits.md)

**Order placement**
- Order types:
  - 1 = Limit;
  - 2 = Market ("MPP: Market Price Protection");
  - 3 = Stop (SL-M, MPP);
  - 4 = Stoplimit (SL-L).
- Product types:
  - CNC ("For equity only");
  - INTRADAY (all segments);
  - MARGIN (derivatives only);
  - MTF (approved symbols only).
- Validity: DAY or IOC.
- `offlineOrder` = True for AMO.
- `disclosedQty` for equity only.
- `orderTag`: 1-30 alphanumeric characters.
- `isSliceOrder` splits quantity above the freeze limit, for NSE CM, NFO and BFO only, max 10 slices per request.
- Response code 201 means "made but not acknowledged"; check the order book before retrying.
- Source: [FYERS single-order docs](https://fyers.in/api-docs/v3/api/trading/order-placement/sync/single-order/)
- Docs include sync and async single, multi-order and multi-leg endpoints, plus:
  - **GTT** (single, OCO, modify, cancel, order book);
  - **Smart orders** (smart limit, smart trail, smart step, smart SIP, pause/resume);
  - position exit-by-filters and set/modify stop-loss and target;
  - webhooks/postbacks;
  - price alerts, margin calculators, option chain, futures chain, screeners, expired F&O data, EDIS/TPIN.
  - Source: [FYERS docs index](https://fyers.in/api-docs/v3/getting-started/)
- **Bracket/Cover orders:** FYERS states "Smart Stop-loss and Target have replaced Cover Orders (CO) and Bracket Orders (BO)". A developer reports the API rejecting productType "BO" with "productType must be one of the following: CNC, MARGIN, INTRADAY, MTF". Some FYERS support pages, last updated Jun 2025, still describe BO/CO. — [FYERS community blog](https://fyers.in/community/blogs-gdppin8d/post/set-target-and-stop-loss-directly-from-the-order-window-tRzgjeSA2USSMmy); [FYERS community thread](https://fyers.in/community/support-desk-rc4sjpa1/post/bracket-order-bo-support-in-fyers-api-v3---receiving-invalid-input-keSDXDPwyZLlYP4); [FYERS support](https://support.fyers.in/portal/en/kb/articles/what-are-regular-bracket-and-cover-orders-in-fyers)
- Under the algo framework, market orders auto-convert to MPP. AMO orders are reportedly not permitted for algo trading (`offlineOrder` must be false). — [FYERS notice](https://fyers.in/notice-board/new-sebi-framework-for-retail-algo-trading-from-april-01-2026); [FYERS community blog](https://fyers.in/community/blogs-gdppin8d/post/sebi-s-new-algo-trading-rules-kick-in-on-april-1-here-is-what-changes-Yew3vdG4CgoXk1q)

**Authentication and static IP**
- "Access tokens expire daily at 6:30 AM." Expired or invalid tokens return error codes -8, -15, -16 or -17. — [FYERS Authentication docs](https://fyers.in/api-docs/v3/api/authentication/)
- The refresh-token flow is discontinued; daily 2FA is required. — [FYERS notice](https://fyers.in/notice-board/new-sebi-framework-for-retail-algo-trading-from-april-01-2026)
- A static IP is required only for order placement. Data and other non-trading APIs do not need one. — [FYERS API product page](https://fyers.in/products/api)
- The IP is set in the FYERS API Dashboard, followed by activating a new app ("One app, one IP"). — [FYERS community blog](https://fyers.in/community/blogs-gdppin8d/post/sebi-s-new-algo-trading-rules-kick-in-on-april-1-here-is-what-changes-Yew3vdG4CgoXk1q)
- A third-party service (Quantsapp) sells a shared static IP at ₹250/month + GST per broker. This may conflict with FYERS' "unique IP" rule. — [Quantsapp](https://www.quantsapp.com/brokers/fyers/api)

**WebSockets**
- Data Socket:
  - symbol (quote) updates, index updates, **5-level market depth**, lite mode;
  - **100 symbols (Standard) / 5,000 (Prime)**, counted per user across all connections;
  - the connection is not established if a subscription exceeds the limit.
- TBT (tick-by-tick) socket:
  - **50-level depth**, NFO and NSE equity only, Protobuf format;
  - **1 symbol (Standard) / 15 (Prime)**, with up to 3 connections of 5 symbols each.
- General socket: order, trade and position events, price alerts and EDIS.
- One instance each of the Data and General socket at a time. Auto-reconnect retries up to 50.
- Source: [FYERS WebSocket overview](https://fyers.in/api-docs/v3/api/websockets/websocket-overview/); [FYERS Plans & Limits](https://fyers.in/api-docs/v3/getting-started/plans-and-limits/)

**Historical data**
- Resolutions: 5S, 10S, 15S, 30S, 45S; 1, 2, 3, 5, 10, 15, 20, 30, 60, 120, 240 minutes; D, 1W, 1M.
- Per request: **minute resolutions up to 100 days**, with data from 3 Jul 2017; daily, weekly and monthly up to 366 days.
- Seconds data: last 30 trading days, Prime only.
- `oi_flag` and `cont_flag` are supported.
- Plan history windows:
  - daily: Standard has the last 5 years (from 2021, rolling); Prime has 25+ years;
  - intraday: Standard has the last 1 year (from 2025, rolling); Prime has 5+ years;
  - expired F&O daily: Standard 2 years, Prime 7+ years;
  - expired F&O intraday: 10 requests/day on Standard.
  - Source: [FYERS historical data docs](https://fyers.in/api-docs/v3/api/market-data/historical-data/); [FYERS Plans & Limits](https://fyers.in/api-docs/v3/getting-started/plans-and-limits/)
- Screeners: 50 API requests/day on Standard. — [FYERS Plans & Limits](https://fyers.in/api-docs/v3/getting-started/plans-and-limits/)

**Automation alternatives and marketplace**
- FYERS Automate runs on FYERS Web inside FYERS infrastructure and "already meets the requirements of the new framework". TradingView alerts can connect via webhooks. — [FYERS community blog](https://fyers.in/community/blogs-gdppin8d/post/sebi-s-new-algo-trading-rules-kick-in-on-april-1-here-is-what-changes-Yew3vdG4CgoXk1q); [FYERS API Bridge notice](https://fyers.in/notice-board/api-bridge-subscription-discontinuation-order-placement-changes/)
- Prime includes "Unlimited Automate, FIA, screeners" (Standard: 5 automations). — [FYERS on X](https://x.com/fyers1/status/2085314964047499423/photo/1); [FYERS API product page](https://fyers.in/products/api)
- The docs also list AI integrations (MCP server, "skills", GPT). — [FYERS docs index](https://fyers.in/api-docs/v3/getting-started/)

### Inferences
- On the free Standard tier, a personal platform is limited to:
  - a 100-symbol live watchlist;
  - 1 TBT symbol;
  - 5,000 data calls a day;
  - one year of intraday history.
- Serious backtesting or multi-symbol scanning practically needs Prime (₹4,990 + GST a year), or a separate data source.
- Strategies relying on true market orders, BO/CO or AMO need redesign: MPP and limit orders, Smart SL/Target or GTT, and no AMO from algos.

### Gaps
- I found no FYERS-run third-party strategy marketplace. FYERS' public pages point only to FYERS Automate.
- I found no FYERS documentation on algo-ID tagging fields in the order payload. Generic IDs appear to be broker- or exchange-assigned, not user-supplied.
- I could not confirm the number of static IPs FYERS allows per user (primary and backup) or how often they can be changed.
- The multi-order (basket) maximum per request was not captured.

---

## Q8. Penalties and enforcement examples (2023-2026)

### Takeaway
SEBI has repeatedly used ex-parte interim orders, impounding and disgorgement against unregistered tip providers who presented themselves as "educators". Amounts range from about ₹17 crore to over ₹546 crore. On the algo side, SEBI pressure has been applied mainly through brokers, for example warnings to 100+ brokers over a platform offering assured-return algos.

### Cited Findings
- **Baap of Chart (Mohammad Nasiruddin Ansari):**
  - interim order Oct 2023 impounded ₹17.2 crore;
  - final order Dec 2024 imposed restrictions on 7 entities for up to 1 year, with a cease-and-desist from acting as investment advisers;
  - recovery of ₹18.14 crore began in Dec 2025, with a prohibitory order on 15 Dec 2025.
  - Source: [Bar & Bench](https://www.barandbench.com/news/sebi-bans-baap-of-chart-securities-trading-impounds-172-crore-gained-from-followers); [The Week, Dec 2024](https://www.theweek.in/news/biz-tech/2024/12/03/why-sebi-ordered-finfluencer-baap-of-charts-to-refund-rs-17-crore-collected-from-investors.html); [SEBI recovery order page](https://www.sebi.gov.in/enforcement/recovery-proceedings/dec-2025/prohibitory-order-issued-against-mohammad-nasiruddin-ansari-rahul-rao-padamati-and-golden-syndicate-ventures-in-the-matter-of-unregistered-investment-advisory-by-baap-of-chart-in-rc-no-8754-8755-and-_98362.html)
- **Asmita Patel / Asmita Patel Global School of Trading:**
  - ex-parte interim order dated 6 Feb 2025;
  - about ₹53.67 crore impounded;
  - barred from unregistered IA and RA services and from dealing in securities;
  - tips were routed via Telegram and Zoom under the guise of courses.
  - Source: [YourStory](https://yourstory.com/2025/02/sebi-bans-fininfluencer-asmita-patel-5-others-from-mkt-impound-illegal-gains-of-over-rs-53-cr); [5paisa](https://www.5paisa.com/news/sebi-seizes-rs5367-crore-from-asmita-patel-global-school-of-trading)
- **Avadhut Sathe Trading Academy (ASTAPL):**
  - interim action in Dec 2025;
  - a final order (reported as issued Fri 23 Oct 2026, 171 pages) directs a refund of ₹546.17 crore plus ₹67.87 crore interest (12% p.a.) within 5 months;
  - penalties total ₹11.5 crore (₹6 crore academy, ₹4 crore Avadhut Sathe, ₹1.5 crore Gouri Sathe);
  - market bans of 2 years (6 months for Gouri Sathe);
  - SEBI found investment advice and research recommendations given via paid programmes, sessions and WhatsApp groups without IA or RA registration.
  - The final-order date and penalty split come from news reports and should be verified on sebi.gov.in.
  - Source: [Moneylife](https://www.moneylife.in/article/sebi-orders-avadhut-sathe-trading-academy-to-refund-546-crore-imposes-115-crore-penalty/82020.html); [LiveLaw Biz](https://www.livelawbiz.com/securities-law/sebi/securities-and-exchange-board-of-india-orders-avadhut-sathe-trading-academy-refund-546-crore-investors-imposes-11-crore-penalty-555837); [Business Standard, Dec 2025](https://www.business-standard.com/amp/markets/news/avadhut-sathe-finfluencer-sebi-ban-disgorgement-unregistered-advisory-125120500178_1.html)
- **Algo platforms:**
  - Oct 2024: over 100 brokers received SEBI warnings for allowing APIs of algo platform TradeTron, which allegedly offered assured returns;
  - a 2022 SEBI communication barred brokers from associating with platforms offering assured returns.
  - Source: [Business Standard, Oct 2024](https://www.business-standard.com/amp/markets/news/sebi-scrutinises-brokers-linked-to-algo-trading-with-guaranteed-returns-124100901218_1.html)

### Inferences
- The recurring fact pattern is: an unregistered person; stock-specific calls, often live during market hours; consideration via course fees or groups. A multi-user signal platform without RA registration would match it.

### Gaps
- I found no specific 2025-2026 SEBI order against an individual algo-software seller (as opposed to finfluencers or brokers). Searches surfaced only explainers.
- I did not retrieve the primary SEBI orders for Asmita Patel or Avadhut Sathe. Figures come from press reports, which differ slightly (for example ₹53.67 crore vs "about ₹54 crore").
