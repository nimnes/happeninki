# Selecting worthwhile events for Häppeninki

Research completed 9 October 2026, Europe/Helsinki. Repository inspected at `9fff441`. This is a research proposal: no production settings, publishing behavior or account connections were changed.

## Recommendation

Use a hybrid selector: explicit exclusions first, an evidence-based model classifier second, a small deterministic ranking third, and a persistent daily posting limit last. Add event-specific web coverage only after the basic selector has been evaluated. Do not make internet discussion, streaming popularity, or an AI's recollection of an artist a prerequisite for publication.

The most useful initial model task is **“What kind of event is this, who is it for, and does it meet these specific preferences?”**, rather than **“Is this interesting?”**. Interest is subjective and the present preferences are mostly exclusions. The latter question would invite the model to invent a taste profile or confuse well-written advertising with a worthwhile event.

Keep the currently approved concert venues and church classical/choir/jazz exception during the first experiment. Model-assisted classification can improve audience and format detection without immediately expanding coverage. Once tested, venue eligibility could become a modest ranking signal instead of a gate; that is a later policy choice, not a change made by this research.

The smallest useful next step is a **preview-only comparison** of the current rules and a structured classifier on about 100 diverse listings, with reasons and a proposed top five. Separately design the daily quota ledger. Avoid connecting multiple social networks or building a full recommendation engine first.

## What the system actually does today

The bot scans six Tampere-area municipalities up to 180 days ahead, plus SYÖ! campaigns and Art Master's own city list. It collects and filters before translation, persists event history in SQLite, and saves state through a GitHub release. The initial posting window is one month. The default translation model is `gemma4:31b-cloud` on Ollama Cloud. The bot budget is 1,080 seconds, and the workflow budget is 25 minutes.

Current publication order is start date and title. `max_events_per_run = 100` limits event records in one invocation, not daily new messages. A selected event can produce a Russian and an English message. Remaining records stay pending; manually running again can publish another batch. Consequently, merely reducing this value does not create a reliable daily quota or remove uninteresting events.

There is no current interest score, artist entity identifier, feedback history, attention evidence, or publication timestamp. Publication receipts preserve message IDs and fingerprints, which is valuable and should remain intact.

### Snapshot audit performed for this research

I replayed the current filters on the Tampere `area-28` API snapshot retrieved earlier on 9 October, covering 9 October–7 December 2026. I did not fetch the entire six-municipality production scan or restore the live Telegram publication database.

| Stage or exclusion | Records |
|---|---:|
| Raw calendar records | 931 |
| Outside mapped cultural categories | 246 |
| In mapped categories | 685 |
| Accepted by current filters and successfully parsed | 265 |
| Music outside selected artists/venues/church exception | 154 |
| Children's activities | 72 |
| Theatre without confirmed permitted language | 63 |
| Reading activities | 60 |
| Standup | 36 |
| Lectures | 15 |
| Nightclub venues or wording | 9 |
| Workshops, games and courses | 11 |

The exclusion rows are mutually exclusive first-match reasons, not independent counts of every rule an event triggers. Accepted records had 265 unique source IDs. This is a **60-day inventory**, not daily new-event arrivals, projected posts, precision, or evidence that all 265 are interesting. It supersedes earlier sample counts taken before the venue expansion and church exception.

Audit metadata, snapshot hash, selected source IDs, current decisions and exact pilot queries are saved in [event-selection-pilot.json](event-selection-pilot.json). The full raw snapshot is temporary and not committed; the hash identifies what was audited but does not guarantee that a future API replay will return the same data.

### Concrete limitations found

1. **Venue matching includes the street.** A Telakka concert is accepted because its address contains “Tullikamarin aukio”, matching the “Tullikamari” substring. Match normalized venue identities and aliases, not the whole address. This is a matching bug, not a judgment about Telakka's programme.
2. **Audience detection remains incomplete.** A listing for schoolchildren's library films passes. Its title uses `Koululaisten` and its description explicitly identifies children's films; the current patterns miss that combination. A classifier could recognize the intended audience without requiring the exact Finnish phrase already encoded.
3. **Theatre identification remains incomplete.** A musical is tagged `movies` and passes, despite its description referring to live musical theatre. The existing language restriction runs only after a listing is recognized as theatre. Genre/format must be established before the performance-language gate.
4. **Equivalent performances can appear twice.** Two Philharmonia listings share title, date and G Livelab venue but differ in address spelling and end time. Exact canonical fingerprints will not necessarily merge them. Normalize identity conservatively and check same-venue, same-start duplicates before ranking.
5. **A church venue does not imply a desired church concert.** A family meal at a church also passes as food. There is not yet a user label specifically for this event, but it is a useful audience/format review case. Do not treat the church exception as permission to admit every activity at a church.

These findings justify improving classification and identity before adding expensive attention measurements. They are documented here; production fixes were outside this research request.

## Separate three different questions

| Question | Useful evidence | Evidence that does not answer it |
|---|---|---|
| Does this event fit the feed? | Event format, audience, genre, actual performance language, municipality, explicit preferences | Number of search results |
| Is the artist established or widely listened to? | Correctly matched artist identity, audience statistics, editorial history | Venue alone; an AI saying it recognizes the name |
| Is this particular event attracting attention? | Dated, event-matched editorial coverage or independently authored discussion | Old reviews of the artist; syndicated ticket listings |

All three can inform selection, but preference fit has priority. A highly discussed children's show is still excluded. A choir performance with little online discussion can still be an excellent match. A positive review in Finnish does not establish that a play is performed in English or Russian.

## Options compared

| Approach | Strength | Main weakness | Role for Häppeninki |
|---|---|---|---|
| Existing rules and venue list | Cheap, explainable and predictable | Incomplete wording and metadata; venue false matches | Keep as baseline and explicit policy |
| Model reads only the listing | Can classify mixed formats and multilingual audience descriptions | Cannot verify fame, attendance or current buzz; errors need validation | Best first addition, in shadow mode |
| Web search and editorial coverage | Finds evidence about the exact event beyond organizer copy | Sparse coverage, duplicate promotion, date/location confusion | Small bonus for borderline candidates |
| Artist audience statistics | Quantitative evidence of reach | Identity ambiguity; coverage and genre bias; not personal fit | Optional music enrichment later |
| Direct social-platform monitoring | Potentially captures genuine conversation | Access, pricing, retention and local coverage vary | Defer; no broad scraper needed initially |
| Personal feedback | Measures actual preference directly | Requires deliberate labels and enough examples | Highest-value learning input |
| Hybrid with persistent daily cap | Combines predictable exclusions and selective discovery | More state and evaluation work | Recommended eventual architecture |

### Why not simply ask the model for a score out of 100?

A score has no stable meaning without a rubric and labeled examples. Two prompts can give different values to the same event. A model may recognize a famous name while overlooking that this is a lecture, tribute act, children's production, or show in an unsuitable language. Confident prose is not calibrated confidence.

Research offers useful techniques but not validation for this application. A study of LLM movie recommendation found less popularity bias than the traditional baselines in its experiment; that does **not** establish a universal bias direction or reliable judgments about Finnish concerts. We should measure our own genre, language and small-event errors. [Lichtenberg et al., popularity-bias study](https://arxiv.org/abs/2406.01285).

Pointwise, pairwise, listwise and setwise prompting are different ranking strategies. Research reports efficiency advantages for setwise document ranking, but document relevance is not local cultural preference. Start with independently cached classifications; if their scores cannot distinguish a small shortlist, test pairwise comparison only on that shortlist. Avoid comparisons over hundreds of events. [Zhuang et al., setwise ranking](https://arxiv.org/abs/2310.09497).

## What a model should classify

Ask for a small validated record with fields such as:

- Event format: concert, festival, exhibition, play, musical, lecture, workshop, nightclub party, community service, or unknown. Allow secondary formats.
- Audience: adults/general, primarily children/families, mixed, or unknown; identify supporting wording.
- Genre: classical, choir, jazz, other music, or unknown. Preserve multiple genres.
- Performance language: English, Russian, Finnish, nonverbal, mixed, or unknown; distinguish it from listing language, subtitles, and original-work language.
- Performers: names actually appearing in the listing, with role: headliner, support, tribute subject, composer, narrator, or past collaborator.
- Preference relation: explicit match, compatible but unspecified, explicit exclusion, or unresolved.
- Evidence references: field and character span supporting each factual label, plus short reason codes.

Return unknown when evidence is missing. Bach or Mozart is ordinarily a composer, not the performer whose streaming audience should be looked up. A band mentioned as a past collaborator is not automatically the headliner. A youth-named choir can give an adult-facing concert; do not confuse performers' ages with target audience. Ticket availability for children likewise does not make a general concert a children's event.

Classify directly from the original Finnish/Russian/English description before translation. This avoids using a translation that may omit the audience or language qualification. Translate only editorially selected events. Clip HTML, keep relevant paragraphs rather than an arbitrary beginning where feasible, and preserve explicit language/age statements near the end.

The repository already requests JSON for translations and validates the result. Ollama's current documentation explicitly says Cloud does not support structured-output enforcement, even though its generic/local API documentation includes JSON/schema controls. A cloud classifier therefore needs local validation and a bounded retry; schema-shaped prompting alone is not a guarantee. [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs).

Keep the classifier without tools, browsing privileges or publication authority. Listing content and search snippets are untrusted data, never instructions. Require known enum values, maximum lengths, valid references into supplied text and no invented external facts. Freeze the model, prompt and preference versions; temperature zero is helpful but should not be treated as an absolute repeatability guarantee. Record returned model identity and token/duration metadata where provided. [Ollama chat API](https://docs.ollama.com/api/chat).

## Internet attention: useful when matched and deduplicated

### A small manual pilot

I executed eight web-search queries on 9 October 2026 for two policy-compatible candidates and six counterexamples or review cases. This was a qualitative search-and-read pilot using the research browsing tool, **not** a benchmark of Brave/Tavily, a paid model classification experiment, or an artist-statistics experiment. Findings are limited to the results surfaced; absence of a matching result does not prove absence of discussion.

| Case | Search observation | Selection lesson |
|---|---|---|
| Candomino cathedral concert | A parish-hosted listing, choir-related material and ticket listing surfaced; no independent event-specific review was established in this pilot | Choir/classical preference can justify inclusion without a buzz threshold |
| Timo Lassy at G Livelab | An original cultural article identifies the Tampere date and combined film/concert programme | Event-matched editorial coverage can be a useful ranking bonus |
| Daycare exhibition supplied by user | Query mainly surfaced irrelevant phrase matches | No results is unknown visibility; the user label already establishes exclusion |
| Local musical programme supplied by user | Another city-organized listing surfaced, including several appearances | Repetition across municipal listings is distribution, not independent demand |
| Moomin dance show supplied by user | Sector and city pages identify it as a family event | Professional production and visibility do not override the audience exclusion |
| Augusta programme supplied by user | No relevant exact-title result established in returned results | Keep the supplied exclusion; do not infer popularity from missing coverage |
| Guitar lecture-concert supplied by user | Organizer programme confirms the lecture-concert format | More visibility cannot turn an excluded lecture into an eligible concert |
| Tootsie musical, a new audit case | An original positive review and other listings surfaced; review credits identify a Finnish translation | Attention and positive reviews do not override the language requirement |

The Candomino programme is supported by the [parish event listing](https://tampereenseurakunnat.fi/en/event-search/et-in-terra-pax/). The Timo Lassy article is dated 19 September and explicitly identifies the 9 October Tampere performance: [original Kulttuuritoimitus coverage](https://kulttuuritoimitus.fi/artikkelit/artikkelit-musiikki/kun-saksofoni-palaa-dokumentti-vie-katsojan-timo-lassyn-maailmaan-elokuvanaytos-ja-konsertti-samana-iltana/).

The family's intended audience is explicit on the [Circus & Dance Finland programme](https://circusdance.fi/esityskalenteri/tanssiva-muumilaakso/). The lecture format appears in the [Tampere Guitar Autumn programme](https://www.tgf.fi/concerts). The Tootsie review is dated 24 August and names the Finnish translator; it is evidence about this production, not a performance-language statement for every date: [original review](https://kulttuuritoimitus.fi/kritiikit/kritiikit-teatteri/antti-paakkonen-on-taydellinen-tampereen-komediateatterin-tootsie-musikaalin-paarooliin/).

### Proposed retrieval and evidence rules

Use one precise query combining original title, city, venue and year; one relaxed artist/title query only if needed. Search Finnish first for local material, then English or Russian when relevant. Do not translate proper names into invented equivalents. Treat an annual festival's year and a touring production's city as identity constraints.

Each matched page should be labeled organizer, venue, ticket seller, syndicated calendar, original editorial article, or independent attendee discussion. Separate **existence confirmation** from **attention**. Three copies of the same ticket description count as one promotional origin and no independent attention bonus. An organizer's “international sensation” phrase is a claim, not established audience evidence.

For attention, require an event identity match: title/performers plus venue/city and date or production season. A movie review, historical performance, or general artist interview should not automatically count for the current concert. Reviews after a performance cannot be used to simulate pre-publication decisions for that performance; avoid this leakage in evaluation.

Cap the bonus. One relevant original editorial piece can be enough for the maximum first-stage editorial boost; ten similar articles should not overwhelm preference fit. Independent discussion is supporting evidence, not an attendance forecast. Preserve no-result, unavailable, ambiguous, and verified-negative states separately.

Raw search-result counts, calendar view counters, follower totals without identity checks, and “sold out” advertising are poor primary ranking features. They measure exposure, distribution or promotional claims, and cannot establish that the event fits this audience. A verified cancellation or lack of tickets belongs in practical availability handling, not the popularity score.

## Provider feasibility and current access

All provider facts below were checked against primary pages on 9 October 2026. Published prices are USD, before taxes; account access and actual Finnish-language coverage were not authenticated or benchmarked.

| Provider | What it offers | Current constraints and assessment |
|---|---|---|
| Ollama Cloud, already used | Listing classification through existing model calls | No schema enforcement in Cloud; reuse validation/caching design, measure actual model cost and latency |
| Brave Search | Web/news results with URLs and snippets | Public Search price $5/1,000 requests, $5 monthly credits and stated 50 QPS; key required. Good candidate for an independent index, subject to storage rights |
| Tavily | Search and optional extraction | 1,000 free monthly credits; basic search 1 credit, advanced 2; pay-as-you-go $0.008/credit. Key required. Candidate for a small research-oriented trial |
| Last.fm | Artist listeners, plays, tags and similar artists | Artist name or MusicBrainz ID; API key required. Useful reach proxy, not monthly Spotify listeners or event attendance |
| MusicBrainz | Artist identity, aliases and metadata | No read API key; meaningful User-Agent and at most one call/second. Identity service, not popularity service |
| Spotify | Artist catalog information; personal affinity with separate authorization | Artist popularity field is deprecated. Development mode requires app owner's Premium account and supports up to five authenticated users. Avoid making deprecated popularity the foundation |
| Reddit | Searchable discussion where authorized access is available | OAuth required; eligible free access documents 100 QPM averaged over a window. Approval/purpose restrictions must be checked, not assumed from that limit |
| X | Paid post access and search ecosystem | Current model is pay-per-use; published post reads $0.005/resource. Small result sets could be affordable, but local usefulness is unmeasured |
| Facebook/Instagram | Potentially valuable local organizer/audience material | A usable broad public-event/discussion workflow was not verified from official docs in this research; exclude from initial dependency plan |
| Bluesky | Potential public discussion | Documentation retrieval did not establish a deployable search/access contract here; coverage and access remain unverified. Optional later test |
| Google Custom Search JSON | Legacy programmatic search | Closed to new customers; existing users must transition by 1 January 2027. Unsuitable new dependency |
| Bing Search APIs | Legacy programmatic search | Official retirement date 11 August 2025. Do not build a new integration on old tutorials |

Search sources: [Brave pricing and API FAQ](https://brave.com/search/api/), [Tavily credits](https://docs.tavily.com/documentation/api-credits). Artist sources: [Last.fm artist endpoint](https://www.last.fm/api/show/artist.getInfo), [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API), [Spotify artist reference](https://developer.spotify.com/documentation/web-api/reference/get-an-artist), [Spotify quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes). Social sources: [Reddit API wiki](https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki), [X pricing](https://docs.x.com/x-api/getting-started/pricing). Legacy search: [Google service notice](https://developers.google.com/custom-search/v1/overview?hl=en), [Microsoft retirement notice](https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement).

### Retention and usage affect the design

Brave's FAQ says durable storage needs a plan explicitly granting storage rights, and its general terms restrict storage beyond transient operation and some AI-improvement uses. Do not assume the base-priced plan allows saving a reusable result corpus in the release database or using it for model evaluation. The required account terms must cover the chosen use; if they do not, omit this provider or limit it to permitted transient processing. Derived scores are not automatically a loophole. [Brave API terms](https://api-dashboard.search.brave.com/documentation/resources/terms-of-service).

Last.fm's terms distinguish non-commercial use and commercial permission, include attribution conditions, and address public access to API-based pages. Confirm the planned use before adopting audience data for a public or monetized feed. Exact commercial cost and a fixed universally applicable quota were not established here. [Last.fm terms](https://www.last.fm/api/tos).

A search API does not grant the rights to republish full publisher articles. Store only what the selected contract allows; for direct editorial sources retain permitted minimal identity/evidence rather than copied articles. Do not collect attendee identities just to count attention. Keep preference feedback on events/genres rather than profiling individuals.

## A proposed decision and scoring design

All numbers in this section are **illustrative starting values, not measured probabilities or validated production thresholds**.

### Eligibility gates

First handle municipality, valid dates, cancellations, explicit user exclusions, and performance-language requirements. A positive signal never overrides an explicit exclusion. Ambiguous theatre language remains unresolved/excluded under the current policy, regardless of popularity. Do not let a model's prior knowledge establish performance language.

During phase one, retain venue/artist/church eligibility. Classifier findings can add a review flag in preview; they do not silently override production policy. A future broader shadow candidate pool must be collected before the venue filter, otherwise the model cannot assess an interesting performance already discarded during parsing. Keep that pool separate from publish eligibility.

### Deterministic score from explicit features

| Component | Maximum | Example evidence |
|---|---:|---|
| Stated preference fit | 40 | Explicitly preferred church classical/choir/jazz, favourite artist; generic compatible culture receives less |
| Appropriate event format and audience | 15 | A performance/exhibition for adults/general audience, backed by source wording |
| Approved programme context | 10 | Selected concert venue or the church exception; identity matched correctly |
| Usable practical information | 10 | Reliable location, occurrence and ticket/availability information where relevant |
| Publication timing | 10 | Useful lead time; not already finished or six months away without reason for early notice |
| Novelty | 5 | New programme, not a duplicate or another post for the same run of performances |
| Verified external interest | 10 | Event-matched independent coverage, or correctly matched audience evidence |

A compatible church choir can score well without the last component. A music event with a famous artist still fails if the event is a lecture or nightclub party. The model returns factual features and a preference-fit category; code applies weights and gates. Do not have it fabricate a point breakdown using facts that were not supplied.

An initial preview could test a minimum of 60/100 and a maximum of five new events per day **per channel**, with alternatives of three and seven. These are suggestions for evaluation; the user has not chosen a quota. Empty slots stay empty. The cap is a ceiling, not a target. Genre diversity can break close ties; it must not force a weak listing into the feed. At most two listings from the same venue/programme in the shortlist is a possible soft rule, with explicit exceptions for genuinely separate high-value events.

Show score components, hard reasons, evidence availability and unresolved fields in preview. Example: “included: choir concert in a church; source evidence strong; online attention unknown.” Do not display 80% confidence unless it has been calibrated on held-out labels.

### Avoid an endless queue

Persist editorial outcomes separately from send outcomes: rejected by preference, unresolved, selected, skipped by daily limit, scheduled for a later lead-time window, and sent. Rejected events remain available for audits but do not return as ordinary pending posts. A low score is not a temporary Telegram failure.

For cap losers, choose a bounded editorial policy, for example at most three days of reconsideration while there is useful lead time. After that, record “not selected” rather than eventually posting every low-ranked event. Reopen a decision only for material event changes, changed preferences, new substantive evidence, or explicit human override. Far-future events can have an intentional publication window rather than being treated as overflow. Do not reset history or use general requeue to implement ranking.

Transport failures for an already selected event can retry within its editorial window, but must consume capacity when they produce a new message. A partly delivered bilingual event needs language-specific receipts and quota handling; it should not be mistaken for a completely unpublished event.

### Enforce a real daily limit

Use the Helsinki calendar day and a durable ledger of successful/reserved new messages by channel and event. Maintain the existing workflow concurrency protection and publication receipts. Multiple manual runs, retries and both languages must read the same persisted quota. Persist progress before continuing; stopping at a fresh per-process counter is insufficient.

Updates and cancellations to already posted messages should not compete with the new-event discovery quota. Nevertheless, continue to bound their runtime and Telegram request rate. An event already posted that now fails a new interest threshold still needs important date, location and cancellation updates. The current shared pending filter would need separate handling for this in a future implementation.

## Caching, failures and deployment fit

Add a classification cache keyed by normalized source text, classifier input fields, model identity, prompt version and preference version. Cache extracted facts separately from preference scoring so changing tastes does not necessarily require re-extraction. Classify once for both channels; do not pay for separate Russian and English judgments of the same source.

Store event decision history and any permitted external evidence separately from `Event` and its publication fingerprint. Popularity or model-score changes should not edit Telegram posts or invalidate translation caches. Proposed additions are tables for classifications, evidence/expiry, selection decisions, feedback, and the daily publication ledger. A schema migration must preserve all existing receipts and recovery behavior.

Use provider-specific expiration and retention. For permitted artist evidence, a weekly/monthly refresh is a reasonable starting experiment; event-specific coverage might refresh once near publication. Successful classifications only rerun on material source changes. Do not cache a network failure as “zero listeners” or “no discussion.” Respect storage rights rather than saving all search snippets forever.

External-search failure removes only the bonus. Classifier failure uses a valid cached classification or holds the unresolved new candidate; it must not automatically accept everything. During shadow mode, failures leave current production unchanged. Known deterministic positive cases may eventually have an explicit capped fallback, but only after evaluation. Preserve cancellation processing and existing source-failure blocking.

Put strict budgets on candidates, searches, fetches, retries and elapsed time. Process exclusions and duplicates first; enrich only borderline candidates. Reserve time for state checkpoints, updates and delivery. With the existing 18-minute bot limit, 100 sequential model requests each lasting ten seconds would already take about 1,000 seconds before translation, scraping or sending. That is a workload illustration, not a latency measurement. Begin with perhaps 20 uncached classification candidates and five borderline search candidates per run, and measure actual p50/p95.

## Cost illustrations

Ollama's currently published `gemma4` rate is $0.14 per million input tokens and $0.40 per million output tokens. Its current public plans use usage credits. The exact billing/availability mapping for the repository's `gemma4:31b-cloud` tag and the user's account was not authenticated, so the calculations below are scenario estimates using the published family rate, not a promise about that account. [Ollama pricing](https://ollama.com/pricing).

Assume 1,000 input tokens and 200 output tokens for each new classification, a 30-day month, no retries, and no cache savings:

| Scenario | Monthly calls | Classification-only estimate |
|---|---:|---:|
| 20 newly classified events/day | 600 | $0.132 |
| 100 newly classified events/day | 3,000 | $0.66 |

The formula is calls × `(1,000 × input_rate + 200 × output_rate) / 1,000,000`. It excludes translations, longer prompts, searches, taxes and subscriptions. Few-shot examples, retained evidence and long descriptions can multiply input length. Collect actual usage before deciding a monthly budget.

For five search candidates per day and two searches each, 300 monthly queries would cost $1.50 gross at Brave's listed rate, potentially covered by its $5 monthly credit. Equivalent Tavily basic searches consume 300 credits; advanced searches consume 600, each within its published 1,000-credit allowance before other usage. At 40 search candidates/day and two searches, 2,400 queries cost $12 gross on Brave, or consume 2,400 Tavily basic credits ($11.20 for the 1,400 above the free allowance at pay-as-you-go rates). Storage/extraction plans can add cost. These are arithmetic scenarios, not provider benchmarks.

At X's published read rate, retrieving ten posts for each of 300 event searches would be 3,000 post reads, or $15 before additional resources/operations and applicable deduplication. This is why “count online discussion everywhere” is a materially different workload from a few selective web queries.

## Evaluation before production changes

Build a 100–150 event set spanning music, church concerts, festivals, food, exhibitions, theatre, children's listings and sparse descriptions. Include the user's explicit negative links and the four real church/venue-friendly candidate types. The unavailable children’s link remains a user-provided negative, not a verified source-text example; reacquire it before testing text classification.

User labels should be: want to see, acceptable if space, skip, or insufficient information, with an optional reason. The user's supplied exclusions are strong labels; an analyst's inference or a model's own answer is not equivalent to ground truth. Positive church policy labels establish eligibility, not that the user loves every specific choir. Include mixed events and harder contrasts: child performer versus child audience, free child tickets versus children's show, headline artist versus tribute subject, subtitles versus performance language, concert versus DJ party, and church venue versus a church mentioned in the biography.

Separate development and held-out sets by artist/production family, not randomly by repeated listing. Use a later time slice as a second test. Keep occurrence dates and evidence acquisition times so future reviews cannot leak into historical ranking. Include English and Russian theatre examples, transliterations and ambiguous names, and separately report Finnish/non-Finnish classification errors.

Compare four variants on the same input: current rules; rules plus classifier; classifier plus external bonus; combined selector plus threshold, deduplication and cap. Repeat classifier runs on 20 ambiguous cases to measure decision stability. Test removal of promotional adjectives and venue names to detect unsupported reliance on prestige or writing quality. Adversarial cases should include instructions embedded in organizer text and fabricated popularity claims.

Measure:

- Precision among the first K selected events, and fraction explicitly labeled skip.
- Recall of “want to see” events in the candidate inventory and those eligible for a particular day. Report inventory recall separately from cap-constrained delivery recall.
- False inclusion by excluded format and false exclusion of preferred church/choir/jazz candidates.
- Artist/venue identity precision, duplicate publication rate and uncertainty/abstention rate.
- Daily new messages per channel, including manual runs and partial-language retries; backlog age and expired editorial decisions.
- Extra classifier/search calls, actual tokens, cost and p95 runtime; impact on translation and delivery budget.

Suggested acceptance targets are at least 90% precision among labeled top-five choices, no violations on the explicitly supplied exclusion examples, and no missing preferred church cases in the dedicated regression set. They are product goals, not demonstrated results. With few labels the uncertainty is large; report counts and confidence intervals rather than declaring success from five examples. Feed reactions or aggregate views could be supplementary feedback later, but there is no verified user-feedback channel in the current implementation and views are not personal interest labels.

## Phased implementation plan

1. **Correct and observe the baseline.** Fix venue identity matching, missing child-audience wording, musical recognition and conservative same-performance deduplication. Add preview exclusion reasons and daily arrival counts. Preserve receipts. Each production change requires ordinary review and tests.
2. **Run a classifier in shadow mode.** Add cached structured extraction and a read-only comparison report. Keep publishing under existing approved rules. Ask the user to label a short, balanced set rather than hundreds of listings.
3. **Add deterministic ranking and persistent quotas.** Tune weights/threshold against held-out labels; separate editorial rejection from retry; reserve update/cancellation handling; make preview exactly reflect the proposed selections.
4. **Trial selective web evidence.** Compare a small number of borderline cases with and without external coverage. Choose a provider only after checking actual access, result quality and retention terms. Adopt it if it improves top-K relevance enough to justify complexity.
5. **Consider artist data or broader discovery.** Resolve identities before statistics, use audience reach only as a capped bonus, and preserve small-event coverage. Convert venue gates to ranking context only if the user accepts the preview results. No fine-tuning or multi-platform social aggregation is needed initially.

## What is established and what remains unknown

Established: current code has a per-run batch limit rather than a daily quota; the replay and manual web queries above were executed; source metadata and wording gaps produce concrete errors; exact-event editorial evidence exists for at least one policy-compatible jazz candidate; attention also exists for a production that should not bypass the theatre-language policy; relevant provider constraints and published prices were checked.

Not established: classifier accuracy, actual `gemma4:31b-cloud` token billing/latency on this account, artist match coverage, Finnish regional search coverage by a selected provider, social-platform adoption value, user-approved positive labels for individual events, a preferred daily quota, or measurable benefit from the proposed scoring weights. No paid API calls, new account registrations, Telegram posts, production changes, commits or pushes were performed for this research.

The practical choice is to test **classification plus explicit preferences and a real posting ceiling first**, then evaluate external attention as an optional improvement. This answers the spam problem directly without turning internet visibility into a requirement for worthwhile culture.
