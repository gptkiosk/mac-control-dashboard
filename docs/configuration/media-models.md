# Media models (fal.ai)

Agents, then **Billing & rates**, then **Media models** lists the image and video models used to make site art and motion media, with what each costs and which quality tier it serves. It is a catalog: it records facts and your own prices and does not start any generation or limit any spending.

## What is listed

Each model shows its fal endpoint id, its billing unit (per image or per second of video), a quality tier (draft is the cheapest, standard the default, premium the best) and a note. Listed prices are fal's published prices from the date shown and are approximate: resolution, duration and audio change the final cost. A blank price means fal's pricing page did not list that model (Veo 3.1 at the time of writing). Look up the live figure with the media tool's `price` command, or enter your own; a price you enter replaces the listed one for display.

## The fal key

Save the key in **Profile, Private credentials, fal.ai key**. It is encrypted, write-only and never shown again, and agents never receive it. Create it at fal with the **API** preset (model execution and storage) and restrict its allowed models to the patterns the panel shows, so a mistake or a leaked key cannot call other models. Set a credit limit at fal as well: MCD does not cap media spending.

The media tool in a project (`tools/media/media.py`) reads `FAL_KEY` from your own shell for now; it cannot read the saved key. Saving it here records the key for future MCD-run generation and shows its status in the catalog.

## Changing the catalog

The model list is in `apps/api/media_catalog.py`. Add a model there with its endpoint id, unit, listed price (or none) and tier; the panel and `GET /api/media/models` pick it up.
