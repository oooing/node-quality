# UI conventions

The compact desktop interface uses locally maintained HTML controls and shared CSS tokens. The visual hierarchy follows the neutral, compact approach of shadcn/ui Nova; this is not a React/shadcn installation.

- One settings center: node sources, recommendation preferences, automatic checks.
- Native dialog, form, select and checkbox semantics; keyboard-operated settings tabs.
- Lucide 0.468.0 SVG source embedded in index.html; license bundled with the installer. No CDN or icon runtime.
- Existing CSS transitions only, with reduced-motion support. No Motion runtime is needed for these interactions.
- Existing state and scheduler retained. No duplicate state manager, layout or drag dependency is introduced without a corresponding feature.
- Source selection means inclusion in automatic checks, never changing the active Clash subscription.
- Sources removed from a readable Clash list leave the active picker and automatic jobs; historical results remain. Startup, periodic discovery, and explicit reload synchronize deletions. Unreadable configuration files do not imply deletion.

Keep node cards at 132px. Reuse the shared control classes, semantic color variables and one icon source for new UI.
