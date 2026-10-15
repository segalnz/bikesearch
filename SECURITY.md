# Security

Never put API keys, MQTT passwords, private keys or production data in an issue,
pull request, screenshot or log attachment. Use GitHub's private vulnerability
reporting for this repository when enabled; otherwise contact the maintainer
privately before disclosing sensitive details.

`token.txt`, `tokens.txt`, environment files, local deployment profiles and runtime
data are excluded from version control. The publication checker inspects the
exact Git index and suppresses secret values in its output. Deployment archives
use an allowlist with additional credential-file exclusions. Only the DeepSeek
credential is extracted for transfer to the LXC; the GitHub credential is never
installed there. Service credentials are read from environment variables or
files under `/etc/motorcycle-monitor`, readable by the service group only.

The dashboard is read-only and intended for a trusted LAN. It has no authentication;
keep it off the public internet or place it behind an authenticated reverse proxy.
Opening a dashboard page never triggers a scan or a cloud API call. Advert and AI
text is rendered as text, with a restrictive Content Security Policy.

Acquisition restricts schemes, ports, redirects and configured source hosts.
Indexed discovery also checks DNS addresses before introducing a new public NZ
host. Requests are bounded and serial, and challenged/rate-limited hosts stop for
that scan. AI input is untrusted advert text; the reviewer has no command or
browser tools and cannot override deterministic eligibility. Logs do not contain
API request headers or response bodies. Rotate a credential immediately if it has
been disclosed, and remove it from Git history before publishing that history.
