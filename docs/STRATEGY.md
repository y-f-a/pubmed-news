# Strategy v3

## One-line concept
An editorial experiment that turns peer-reviewed medical abstracts into convincing news stories, presented as a local-only gallery for blog screenshots.

## Positioning
- Blog-first, screenshot-driven proof, not a hosted product.
- Admin-curated artifacts with a single fixed prompt for consistency.

## Why it exists
Curious readers want to see how scientific writing becomes narrative. This project makes that visible with source abstracts, the exact prompt, and finished stories.

## Audience
- General public and media-literate readers who enjoy editorial experiments.

## Success metric
- Compelling blog screenshots that convince a general audience.

## Value proposition
"A curated, local gallery where each artifact shows the abstract, the exact prompt, and the final article."

## Public outcome
- The public-facing artifact is a blog post with screenshots.
- The app is run locally for curation and capture; no public hosting.

## V1 product scope (local)
Core
- Admin-only PubMed search with full abstracts in results.
- Admin generate and publish flow.
- Gallery index of curated items, ordered by featured rank.
- Story page with a single news story view and a left nav to Abstract and Prompt.
- Prompt stored and displayed verbatim with each artifact.

Quality and safety
- SQLite is the system of record for cached PubMed results and published artifacts.
- Admin-only generation; no public generation variants.

## V1 local flow (screenshot)
1) Run locally.
2) Curate 9 artifacts in admin.
3) Capture gallery, story, and admin screenshots at 1440x900.
4) Publish screenshots to the blog.

## V1 admin flow
1) Login.
2) Search PubMed.
3) Review abstracts and generate with the fixed prompt.
4) Review the draft story view.
5) Publish as-is and set featured order.

## Content pipeline
1) PubMed eSearch for primary research.
2) eFetch title, abstract, journal, year, authors, DOI.
3) Generate one output with the fixed prompt.
4) Store output, raw prompt, and abstract/metadata snapshot.
5) Publish to the local gallery.

## Interface direction
- Classic newspaper feel with modern-classic serif typography.
- Story-first layout; supporting material follows.
- No imagery or placeholders; text-driven credibility.

## Differentiators
- Single tuned prompt, no framing variants.
- Transparency via raw prompt and abstract snapshots.
- Admin curation ensures intentional selection.

## Risks and mitigations
- Misinterpretation: blog copy and labeling clarify the experiment.
- Quality variance: curator selects the best nine artifacts.
- Cost control: admin-only generation and caching.

## Short plan
Week 1: finalize local UI for screenshots, curate nine artifacts.
Week 2: capture screenshots and publish the blog narrative.
