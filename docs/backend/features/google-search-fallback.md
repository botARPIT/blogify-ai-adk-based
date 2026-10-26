# Google Search fallback

The research stage calls Tavily first. If Tavily fails or returns no usable
sources, `research_topic` tries Google Programmable Search. The research agent
also has a separate Google search tool available if it needs to retry the
search itself. Both providers return an ordered `sources` list for numbered
citations.

Configure these separately from `GOOGLE_API_KEY`, which is used for Gemini
models:

```dotenv
GOOGLE_SEARCH_API_KEY=...
GOOGLE_SEARCH_ENGINE_ID=...
```

Google's Custom Search JSON API requires an API key and Programmable Search
Engine ID. Google currently limits this API to existing customers and says
existing customers must transition by January 1, 2027. See [Google's API
overview](https://developers.google.com/custom-search/v1/overview).

Without those credentials, Tavily remains usable; if Tavily also fails, the
research tool returns a clear zero-source error rather than fabricating sources.
