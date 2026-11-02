# Vendored front-end libraries

Served from here instead of a CDN so the web UI works on a LAN with no internet
access. Unmodified upstream builds; to upgrade one, replace its file(s) and update the
path in `templates/base.html`.

| Library | Version | Source | License |
| --- | --- | --- | --- |
| Bootstrap (CSS + JS bundle) | 5.3.1 | https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/ | MIT |
| Bootstrap Icons (CSS + woff/woff2 fonts) | 1.11.1 | https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/ | MIT |
| jQuery | 3.6.0 | https://code.jquery.com/jquery-3.6.0.min.js | MIT |
| Inter (variable font, `inter/InterVariable.woff2`) | 4.1 | https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip (`web/InterVariable.woff2`) | SIL OFL 1.1 (`inter/OFL.txt`) |

Inter is not linked from `templates/base.html`: `static/css/tokens.css` declares it with
`@font-face`.

SHA-384 of the files as downloaded (same values as the CDN's published SRI hashes):

- `bootstrap/bootstrap.min.css`: `4bw+/aepP/YC94hEpVNVgiZdgIC5+VKNBQNGCHeKRQN+PtmoHDEXuppvnDJzQIu9`
- `bootstrap/bootstrap.bundle.min.js`: `HwwvtgBNo3bZJJLYd8oVXjrBZt8cqVSpeBNS5n7C8IVInixGAoxmnlMuBnhbgrkm`
- `jquery/jquery-3.6.0.min.js`: `vtXRMe3mGCbOeY7l30aIg8H9p3GdeSe4IFlP6G8JMa7o7lXvnz3GFKzPxzJdPfGK`
- `inter/InterVariable.woff2`: `NDj3qtsUEjin1XBDZ9zwBRsJjDf51qDfUnZZfiNICq+3AWnh8dTXCRjW9qQHFnEK`
