# Research and Regulatory Notes

This file records claims safe to use in the writeup and architecture rationale. Re-check volatile facts before publication.

## 1. Global problem framing

### WHO
Use the conservative primary-source framing:

> WHO reports that an estimated **1 in 10 medical products in low- and middle-income countries** is substandard or falsified.

Do not substitute an unsupported “10–15% of the developing-country pharmaceutical market” or “over one million deaths per year” claim unless you can cite the specific methodology and population.

WHO fact sheet:
https://www.who.int/news-room/fact-sheets/detail/substandard-and-falsified-medical-products

WHO has published modeled impact estimates for specific diseases/settings, but those should not be generalized to a universal annual death count.

## 2. India QR context

CDSCO’s FAQ for G.S.R. 823(E), effective 1 August 2023, requires the Schedule H2 top 300 formulation brands to carry barcode/QR information including:
- unique product identification code;
- proper/generic name;
- brand name;
- manufacturer;
- batch;
- manufacturing date;
- expiry;
- manufacturing licence number.

Primary/official material:
https://cdsco.gov.in/opencms/resources/UploadCDSCOWeb/2018/UploadPublic_NoticesFiles/Final%20FAQs%20on%20QR%20code%2021.07.2023.pdf

CDSCO guidance also notes the top-300 rule and API QR requirements:
https://www.cdsco.gov.in/opencms/export/sites/CDSCO_WEB/Pdf-documents/Guidance-for-Identification-and-Verification-of-Spurious-Drugs_.pdf

Important design implication:
QR availability increases the amount of digital identity data but does not automatically make a copied code physically unclonable.

## 3. Pharmaceutical serialization and traceability

### US DSCSA
The US Drug Supply Chain Security Act establishes package-level product tracing / interoperable electronic exchange requirements.

FDA overview:
https://www.fda.gov/drugs/drug-supply-chain-security-act-dscsa/drug-supply-chain-security-act-law-and-policies

### EU Falsified Medicines Directive
EU safety features include a unique identifier and anti-tampering device for relevant medicines.

European Commission:
https://health.ec.europa.eu/medicinal-products/falsified-medicines_en

### GS1 EPCIS
EPCIS is an event data standard for supply-chain visibility, useful as a long-term interoperability target.

GS1:
https://www.gs1.org/standards/epcis

Design implication:
SCADS should model observations/events now so it can map to interoperable event semantics later.

## 4. Why QR cloning is a real technical concern

A relevant research direction explicitly studies serialized QR codes plus copy-sensitive visual features rather than assuming QR alone prevents copying.

Paper:
Picard, Landry, Bolay. “Counterfeit detection with QR codes.” ACM Symposium on Document Engineering, 2021.

Consensus record:
https://consensus.app/papers/details/395b728c193e593c80b9c741b57bed17/

Reported premise:
serialized QR codes can be cloned; copy-sensitive layers can strengthen them.

Another relevant paper:
Yan et al. “An IoT-Based Anti-Counterfeiting System Using Visual Features on QR Code.” IEEE Internet of Things Journal, 2021.

Consensus:
https://consensus.app/papers/details/91ed03354ac157f784b24545980e3967/

It uses natural texture / printed micro-features registered during production and smartphone verification, supporting the long-term physical-fingerprint direction.

## 5. Physical unclonable functions / physical fingerprints

### Smartphone-readable optical PUF direction
Kingsley, Schaffer, Chiarot. “Electrospray deposition of physical unclonable functions for drug anti-counterfeiting.” Scientific Reports, 2024.

Consensus:
https://consensus.app/papers/details/cf0cb72b621f52d7b101533cee768d6a/

The paper demonstrates cellphone image matching of enrolled stochastic patterns, supporting the idea that future SCADS can bind identity to physical randomness.

### On-dose PUF
Leem et al. “Edible unclonable functions.” Nature Communications, 2020.

Consensus:
https://consensus.app/papers/details/23a13052888f59afaa58aa3371471ecc/

This is future research context, not an MVP component.

## 6. Traceability literature

The literature is crowded with blockchain-based pharmaceutical traceability. That means “we use blockchain” is not a credible novelty claim and is not needed for SCADS.

The real product insight is the evidence architecture:
- physical-digital binding;
- event semantics;
- behavioral anomalies;
- calibrated fusion.

A review on pharmaceutical supply-chain traceability:
Haji, Kerbache, Al-Ansari. “Critical Success Factors and Traceability Technologies for Establishing a Safe Pharmaceutical Supply Chain.” Methods and Protocols, 2021.

Consensus:
https://consensus.app/papers/details/4f1f5d776b2b5925b1b0908fbb2dfea4/

## 7. First Commit hackathon constraints

Official event:
https://www.wemakedevs.org/aws/first-commit

Official rules:
https://www.wemakedevs.org/aws/first-commit/rules

As of Sept 18, 2026:
- event dates: Sept 17–20, 2026;
- online across India, optional Bengaluru build day Sept 19;
- 1–4 person teams;
- project work must be built during the event;
- AWS use is required for prizes;
- submission requires public repository, <=3-minute demo, short writeup;
- judges only evaluate submitted material;
- Ship It is for live AWS deployment and architecture/cost matter;
- judging dimensions include idea/impact, AWS, learning, execution and demo.

Always re-open the event page before final submission for deadline/form changes.

## 8. Claims SCADS can make

Good:
- “A valid code can be copied, so identifier existence is not enough.”
- “SCADS combines identity, physical-package evidence and scan history.”
- “The MVP demonstrates synthetic visual tampering and cloned-serial anomalies.”
- “The architecture is designed to evolve toward unit-level physical fingerprints and event-based traceability.”

Bad:
- “SCADS proves a medicine is genuine.”
- “SCADS can detect all counterfeit drugs.”
- “Nobody has combined multiple signals before.”
- “Blockchain solves counterfeiting.”
- “Our synthetic perturbation accuracy equals real-world counterfeit accuracy.”

## 9. Research gap framing

Do not frame novelty as “multimodal fusion has never been done.”

A defensible product/research gap is:

> Many deployed consumer checks are identifier-centric, while many higher-assurance anti-counterfeit approaches require specialized tags, controlled enrollment, additional hardware, or supply-chain integration. SCADS explores a phone-first evidence-fusion architecture that treats identity, registered physical-packaging evidence and scan-history contradictions as independent factors, with an explicit path to stronger manufacturer-enrolled fingerprints and standardized event data.

This is modest and defensible.
