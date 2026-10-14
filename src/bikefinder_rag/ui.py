"""Presentation for the catalogue chat, without network or catalogue reads."""

import gradio as gr
from gradio.themes.utils.fonts import Font


THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.amber,
    secondary_hue=gr.themes.colors.slate,
    neutral_hue=gr.themes.colors.slate,
    font=[Font("system-ui"), Font("sans-serif")],
    font_mono=[Font("ui-monospace"), Font("monospace")],
).set(
    body_background_fill="#f3f2ed",
    body_background_fill_dark="#f3f2ed",
    body_text_color="#202827",
    body_text_color_dark="#202827",
    body_text_color_subdued="#5d6865",
    body_text_color_subdued_dark="#5d6865",
    background_fill_primary="#ffffff",
    background_fill_primary_dark="#ffffff",
    background_fill_secondary="#f7f7f3",
    background_fill_secondary_dark="#f7f7f3",
    border_color_primary="#dce0d9",
    border_color_primary_dark="#dce0d9",
    block_background_fill="#ffffff",
    block_background_fill_dark="#ffffff",
    block_border_color="#dce0d9",
    block_border_color_dark="#dce0d9",
    block_label_text_color="#52605c",
    block_label_text_color_dark="#52605c",
    block_title_text_color="#202827",
    block_title_text_color_dark="#202827",
    input_background_fill="#ffffff",
    input_background_fill_dark="#ffffff",
    input_border_color="#dce0d9",
    input_border_color_dark="#dce0d9",
    input_placeholder_color="#73807b",
    input_placeholder_color_dark="#73807b",
    button_primary_background_fill="#e7b348",
    button_primary_background_fill_dark="#e7b348",
    button_primary_background_fill_hover="#f0c566",
    button_primary_background_fill_hover_dark="#f0c566",
    button_primary_text_color="#18201e",
    button_primary_text_color_dark="#18201e",
    button_secondary_background_fill="#ffffff",
    button_secondary_background_fill_dark="#ffffff",
    button_secondary_background_fill_hover="#f1f3ed",
    button_secondary_background_fill_hover_dark="#f1f3ed",
    button_secondary_text_color="#384440",
    button_secondary_text_color_dark="#384440",
    button_secondary_border_color="#dce0d9",
    button_secondary_border_color_dark="#dce0d9",
    link_text_color="#17644f",
    link_text_color_dark="#17644f",
    link_text_color_hover="#0e4a3b",
    link_text_color_hover_dark="#0e4a3b",
)


HERO = """
<div class="bf-hero">
  <div class="bf-brand"><span class="bf-mark" aria-hidden="true">b.</span>
    <span>bikefinder<span class="bf-wordmark-dot">.</span></span>
    <span class="bf-edition">LE CATALOGUE MOTO</span>
  </div>
  <div class="bf-hero-copy">
    <div><p class="bf-eyebrow">LES FICHES. LES CHIFFRES. LES SOURCES.</p>
      <h1>Chaque moto, ses caractéristiques.</h1>
      <p class="bf-description">Posez votre question, comparez les millésimes et explorez les équipements.</p>
    </div>
    <div class="bf-hero-tags" aria-label="Contenu du catalogue">
      <span>Fiches techniques</span><span>Équipements</span><span>Comparaisons</span>
    </div>
  </div>
</div>
"""


WELCOME = """
<div class="bf-welcome">
  <div class="bf-welcome-mark" aria-hidden="true">↗</div>
  <h2>Une moto en tête ?</h2>
  <p>Donnez son modèle et son année.<br>Vous pouvez aussi comparer plusieurs motos ou filtrer leurs équipements.</p>
  <div class="bf-welcome-example">« La MT-09 de 2021 a gagné combien de cylindrée par rapport à 2020 ? »</div>
  <p class="bf-welcome-note">Les réponses conservent les unités, les sources et les données inconnues.</p>
</div>
"""


CSS = """
.gradio-container {
  max-width: 1440px !important;
  width: 100% !important;
  box-sizing: border-box !important;
  margin: 0 auto !important;
  padding: 16px 24px 12px !important;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
  color-scheme: light;
}
.gradio-container .main { padding: 0 !important; max-width: none !important; }
#bf-header { padding: 0 !important; background: transparent; border: 0; }
.gradio-container .prose { color: #202827; }
.gradio-container .prose a { color: #17644f; text-underline-offset: 3px; }
.bf-hero { background: #182620; color: #f5f5ed; border-radius: 20px; padding: 20px 27px 23px; }
.bf-brand { display: flex; align-items: center; gap: 12px; font-size: 23px; font-weight: 720; letter-spacing: -.7px; }
.bf-mark { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 10px; background: #e7b348; color: #182620; font-size: 27px; }
.bf-brand > span:not(.bf-mark) { color: #f5f5ed; }
.bf-wordmark-dot { color: #e7b348; }
.bf-edition { margin-left: auto; color: #b7c4bc; font-size: 10px; font-weight: 600; letter-spacing: 1.8px; }
.bf-hero-copy { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-top: 19px; }
.bf-eyebrow { color: #c5d0c8; font-size: 10px; letter-spacing: 1.8px; font-weight: 650; margin: 0 0 9px; }
.bf-hero h1 { color: #f5f5ed; margin: 0; font-size: clamp(23px, 2.7vw, 36px); font-weight: 650; line-height: 1.2; letter-spacing: -1.1px; }
.bf-description { color: #c9d2cc; font-size: 14px; line-height: 1.55; margin: 12px 0 0; }
.bf-hero-tags { display: flex; flex-wrap: wrap; justify-content: end; gap: 7px; max-width: 230px; padding-bottom: 2px; }
.bf-hero-tags span { border: 1px solid #43534a; border-radius: 30px; padding: 6px 10px; color: #dce4dc; font-size: 11px; white-space: nowrap; }
#bf-workspace { gap: 22px; margin-top: 3px; align-items: flex-start; }
#bf-main, #bf-side { gap: 14px; }
#bf-chat { border-radius: 17px; border: 1px solid #dce0d9; overflow: hidden; background: #ffffff; height: clamp(310px, calc(100dvh - 420px), 670px) !important; min-height: 310px !important; }
#bf-chat > label { padding: 10px 14px; }
#bf-chat .message { font-size: 14px; line-height: 1.65; border-radius: 12px; }
#bf-chat .message.user { background: #edf1e8; color: #24352b; }
#bf-chat .message.bot { background: #ffffff; }
#bf-chat .prose table { font-size: 13px; border-collapse: collapse; min-width: 100%; }
#bf-chat .prose th { background: #f0f3ec; text-align: left; padding: 11px 13px; white-space: nowrap; color: #24352b; }
#bf-chat .prose td { padding: 10px 13px; border-bottom: 1px solid #e4e8df; vertical-align: top; }
#bf-chat .prose tr:nth-child(even) td { background: #fafbf8; }
#bf-chat .prose table a { overflow-wrap: anywhere; }
#bf-chat a { color: #17644f !important; text-underline-offset: 3px; }
#bf-send:focus-visible, #bf-reset:focus-visible, #bf-examples button:focus-visible { outline: 3px solid #3e7259; outline-offset: 2px; }
.bf-welcome { margin: auto; padding: 22px 20px; max-width: 570px; text-align: center; }
.bf-welcome-mark { display: grid; place-items: center; margin: 0 auto 12px; width: 40px; height: 40px; border: 1px solid #dfe5d9; border-radius: 12px; background: #f4f6ed; font-size: 24px; color: #587047; }
.bf-welcome h2 { color: #25352c; font-size: 22px; font-weight: 650; letter-spacing: -.6px; margin: 0 0 10px; }
.bf-welcome p { color: #607068; font-size: 13px; line-height: 1.6; margin: 0; }
.bf-welcome-example { margin: 14px auto; border: 1px solid #e4e8df; border-radius: 11px; padding: 10px 15px; font-size: 12px; line-height: 1.6; color: #3d5347; background: #fafbf8; }
.bf-welcome .bf-welcome-note { font-size: 12px; color: #738078; }
#bf-composer { gap: 10px; align-items: stretch; }
#bf-question { border-radius: 13px; }
#bf-question textarea { min-height: 53px; font-size: 14px; line-height: 1.5; padding: 14px 15px; }
#bf-send { border-radius: 13px; min-height: 58px; font-size: 14px; font-weight: 650; }
#bf-toolbar { align-items: center; gap: 10px; }
#bf-toolbar-note { font-size: 12px; color: #6d786f; }
#bf-reset { border-radius: 9px; min-height: 34px; font-size: 12px; }
#bf-side-title { padding: 0 2px; }
#bf-side-title h2 { font-size: 15px; font-weight: 700; color: #2b3c31; margin: 1px 0 5px; }
#bf-side-title p { color: #6a776e; font-size: 12px; margin: 0; line-height: 1.5; }
#bf-examples { border-radius: 14px; padding: 0 !important; border: 0 !important; background: transparent; }
#bf-examples .label, #bf-examples label { display: none; }
#bf-examples .samples { gap: 8px; }
#bf-examples table { display: block; border-spacing: 0 8px; width: 100%; }
#bf-examples tbody { display: flex; flex-direction: column; gap: 8px; }
#bf-examples tr { display: block; border: 1px solid #dce0d9; border-radius: 11px; background: #ffffff; transition: border-color .15s, background .15s; }
#bf-examples tr:hover { border-color: #a8b89c; background: #f8faf4; }
#bf-examples td { display: block; padding: 12px 14px !important; white-space: normal !important; overflow-wrap: anywhere; font-size: 12px !important; line-height: 1.55; height: auto !important; max-width: none !important; }
#bf-examples .gallery { grid-template-columns: 1fr !important; }
#bf-examples .gallery-item { text-align: left; padding: 11px 13px; border-radius: 11px; border: 1px solid #dce0d9; font-size: 12px; line-height: 1.5; background: #ffffff; width: 100%; }
#bf-examples .gallery-item:hover { border-color: #a8b89c; background: #f8faf4; }
#bf-examples .gallery-item .gallery { max-width: none; }
#bf-side .bf-guide { border-radius: 12px; border: 1px solid #dce0d9; font-size: 12px; background: #fafbf8; }
#bf-side .bf-guide .prose { font-size: 12px; line-height: 1.65; }
#bf-side .bf-guide .prose p { margin: 9px 0; }
#bf-side .bf-guide .prose strong { color: #344e3a; }
#bf-footnote { padding: 2px 3px; font-size: 11px; color: #778176; line-height: 1.65; }
@media (max-width: 900px) {
  .gradio-container { padding: 15px !important; }
  .bf-hero { padding: 21px 23px; }
  .bf-hero-tags { display: none; }
  #bf-workspace { gap: 18px; }
  #bf-side { min-width: 250px !important; }
}
@media (max-width: 650px) {
  .gradio-container { padding: 10px !important; }
  .bf-hero { padding: 19px; border-radius: 15px; }
  .bf-brand { font-size: 21px; }
  .bf-edition { font-size: 8px; letter-spacing: 1px; }
  .bf-hero-copy { margin-top: 22px; }
  .bf-description { font-size: 12px; }
  .bf-eyebrow { font-size: 8px; letter-spacing: 1.1px; }
  #bf-workspace { flex-direction: column; }
  #bf-main, #bf-side { width: 100%; min-width: 0 !important; }
  #bf-chat { height: 420px !important; min-height: 340px !important; }
  #bf-send { min-width: 86px !important; padding: 0 10px; }
  .bf-welcome { padding: 22px 14px; }
  .bf-welcome h2 { font-size: 22px; }
  #bf-toolbar-note { font-size: 11px; }
}
@media (prefers-reduced-motion: reduce) {
  #bf-examples tr { transition: none; }
}
"""
