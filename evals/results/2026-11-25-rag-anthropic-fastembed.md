RAG eval: provider `anthropic`, embeddings `fastembed`, 15 questions.

Retrieval: top 5, minimum similarity 0.45. Refusal correctness partly measures that threshold: a question with nothing above it is refused without asking the model.

| Metric | Result |
|---|---|
| Answer accuracy (rubric keywords, answerable questions) | 92% |
| Expected source cited | 100% |
| Citation precision (citations to an expected source) | 100% |
| Refusal correctness (unanswerable questions refused) | 100% |
| False refusals (answerable questions refused) | 0 |
| Errors | 0 |

| Case | Answerable | Covered | Rubric | Source | Cited documents | Result |
|---|---|---|---|---|---|---|
| bootcamp-price | yes | yes | ok | ok | 02-pricing-and-payment-plans.md | pass |
| course-installments | yes | yes | ok | ok | 07-faq.md | pass |
| bootcamp-duration | yes | yes | ok | ok | 01-programs-overview.md | pass |
| mentorship-price | yes | yes | ok | ok | 02-pricing-and-payment-plans.md | pass |
| refund-window | yes | yes | ok | ok | 06-refund-policy.md | pass |
| scholarship-how | yes | yes | ok | ok | 03-scholarships.md | pass |
| admissions-steps | yes | yes | MISS | ok | 04-admissions-process.md | FAIL |
| countries | yes | yes | ok | ok | 07-faq.md | pass |
| bootcamp-topics | yes | yes | ok | ok | 01-programs-overview.md | pass |
| live-or-recorded | yes | yes | ok | ok | 07-faq.md | pass |
| es-course-price | yes | yes | ok | ok | 02-pricing-and-payment-plans.md | pass |
| es-bootcamp-hours | yes | yes | ok | ok | 07-faq.md | pass |
| no-job-guarantee | no | no | n/a | n/a | - | pass |
| no-visa | no | no | n/a | n/a | - | pass |
| no-company-invoicing | no | no | n/a | n/a | - | pass |
