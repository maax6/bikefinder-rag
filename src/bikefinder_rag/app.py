"""Gradio UI for the local proof of concept, using Ollama by default.

Optional Anthropic/OpenRouter backends use a visitor-provided API key.
"""

import os
import re
import unicodedata
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import gradio as gr

from bikefinder_rag.agent.loop import (
    BACKEND,
    OLLAMA_MODEL,
    OLLAMA_TURN_TIMEOUT_SECONDS,
    TURN_LIMIT_MESSAGE,
    run_agent,
)
from bikefinder_rag.db.client import get_connection
from bikefinder_rag.ui import CSS, HERO, THEME, WELCOME

CATALOG_EXPERIMENT_ENABLED = BACKEND == "ollama" and os.getenv("BIKEFINDER_CATALOG_EXPERIMENT") == "1"
CATALOG_RESEARCH_ENABLED = BACKEND == "ollama" and (os.getenv("BIKEFINDER_CATALOG_RESEARCH") == "1" or CATALOG_EXPERIMENT_ENABLED)


def _is_retry(message: str) -> bool:
    text = unicodedata.normalize("NFKD", message).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z\s]", "", text)
    return " ".join(text.split()) in {
        "retry", "try again", "retry please", "retente", "reessaie", "reessaye",
        "essaie encore", "reessaie stp", "retente stp",
    }


def _is_final_local_message(message: dict) -> bool:
    return (isinstance(message, dict) and message.get("role") == "assistant"
            and not message.get("tool_calls") and isinstance(message.get("content"), str)
            and bool(message["content"].strip()) and message["content"] != TURN_LIMIT_MESSAGE)


def _completed_local_history(history: list) -> list:
    """Discard incomplete attempts, including legacy ones before later turns."""
    completed, pending = [], []
    for message in history:
        if isinstance(message, dict) and message.get("role") == "user":
            pending = [message]
        elif pending:
            pending.append(message)
            if _is_final_local_message(message):
                completed.extend(pending)
                pending = []
    return history if completed == history else completed


def _previous_question(chat_history: list) -> str | None:
    for message in reversed(chat_history):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip() and not _is_retry(content):
            return content
    return None


def chat(message: str, chat_history: list, api_key: str, agent_history: list):
    api_key = (api_key or "").strip()
    if BACKEND != "ollama" and not api_key:
        chat_history = chat_history + [
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": "Please enter your API key above first — Anthropic "
                           "(console.anthropic.com) or OpenRouter (openrouter.ai/keys).",
            },
        ]
        return chat_history, agent_history

    provider = None
    if BACKEND != "ollama":
        provider = "openrouter" if api_key.startswith("sk-or-") else "anthropic"

    question = message
    previous_state = agent_history
    if BACKEND == "ollama":
        previous_state = _completed_local_history(agent_history)
        if os.getenv('BIKEFINDER_JEV_ROUTER')=='1' and not previous_state and chat_history:
            from bikefinder_rag.agent.loop import _user_text
            previous_state=[{'role':m['role'],'content':_user_text(m)} for m in chat_history[-16:] if m.get('role') in ['user','assistant']]
        if _is_retry(message):
            question = _previous_question(chat_history)
            if question is None:
                return chat_history + [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": "There is no earlier question to retry. Ask your question first."},
                ], previous_state

    conn = get_connection()
    try:
        final_text, updated_history = run_agent(
            conn, None, question, previous_state, provider=provider, api_key=api_key or None
        )
    finally:
        conn.close()

    if BACKEND == "ollama" and not (
        isinstance(updated_history, list) and updated_history
        and _is_final_local_message(updated_history[-1])
        and updated_history[-1]["content"] == final_text
    ):
        # The UI keeps its error bubble; the model only sees completed turns.
        updated_history = previous_state
        if not isinstance(final_text, str) or not final_text.strip():
            final_text = "The local model did not produce a final answer. Please retry."

    chat_history = chat_history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": final_text},
    ]
    return chat_history, updated_history


def clear_conversation():
    """Start a new conversation with no hidden route or model history."""
    return [], [], ""


with gr.Blocks(title="Bikefinder — catalogue technique") as demo:
    gr.HTML(HERO, apply_default_css=False, elem_id="bf-header")
    agent_state = gr.State([])
    with gr.Row(elem_id="bf-workspace"):
        with gr.Column(scale=4, min_width=430, elem_id="bf-main"):
            chatbot = gr.Chatbot(
                label="Votre conversation",
                elem_id="bf-chat",
                height=590,
                min_height=420,
                placeholder=(WELCOME.replace("Donnez son modèle et son année.", "Donnez son modèle ou sa famille. L’année est facultative.")
                             if CATALOG_RESEARCH_ENABLED else WELCOME),
                layout="bubble",
                buttons=["copy"],
                feedback_options=None,
            )
            with gr.Row(elem_id="bf-composer"):
                msg = gr.Textbox(
                    label="Votre question",
                    show_label=False,
                    placeholder=("Une moto ou une famille, votre question…" if CATALOG_RESEARCH_ENABLED
                                 else "Une moto, une année, une question…"),
                    elem_id="bf-question",
                    lines=1,
                    max_lines=5,
                    scale=6,
                    min_width=180,
                )
                send = gr.Button("Envoyer ↗", variant="primary", scale=1, min_width=110, elem_id="bf-send")
            with gr.Row(elem_id="bf-toolbar"):
                gr.Markdown(("L’année est **facultative** pour explorer une famille. Vos relances gardent le contexte."
                             if CATALOG_RESEARCH_ENABLED else "Précisez le **millésime**. Vos relances gardent le contexte."),
                            elem_id="bf-toolbar-note")
                reset = gr.Button("Nouvelle conversation", size="sm", scale=0, min_width=155, elem_id="bf-reset")
        with gr.Column(scale=1, min_width=280, elem_id="bf-side"):
            gr.Markdown("## Pour commencer\nChoisissez une question, puis adaptez-la.", elem_id="bf-side-title")
            question_examples = gr.Examples(
                examples=[
                    ["Donne la fiche technique de la BMW F 900 R de 2020, avec les unités et les sources."],
                    ["Compare la Yamaha MT-09 de 2020 et la Yamaha MT-09 de 2021 dans un tableau : cylindrée, puissance et poids."],
                    ["Quelles motos ont l'ABS en 2000 ?"],
                    ["Quelle est l'autonomie de la CFMoto 800 MT Explore de 2025, avec la source ?"],
                    ["Combien de Yamaha de 2020 ont l'ABS et un shifter de série ?"],
                ],
                inputs=msg,
                label="Exemples de questions techniques",
                elem_id="bf-examples",
                example_labels=[
                    "Fiche · BMW F 900 R, 2020",
                    "Comparer · MT-09, 2020 / 2021",
                    "Équipements · ABS, 2000",
                    "Autonomie · 800 MT Explore, 2025",
                    "Filtrer · Yamaha, 2020",
                ],
            )
            with gr.Accordion("Bien lire une réponse", open=False, elem_classes="bf-guide"):
                gr.Markdown(
                    "**Les fiches sources** accompagnent les caractéristiques. Vous pouvez les ouvrir pour vérifier un chiffre.\n\n"
                    "**Série, option, inconnu** : une donnée absente reste **inconnue**, y compris pour un équipement.\n\n"
                    "**Les poids** gardent leur type : poids sec et poids tous pleins ne sont comparables qu'entre valeurs de même type.\n\n"
                    "**L’autonomie** conserve sa mention d’estimation lorsqu'elle est calculée et non vérifiée."
                )
            with gr.Accordion("Couverture du catalogue", open=False, elem_classes="bf-guide"):
                gr.Markdown(
                    "Le **catalogue enrichi Motoplanète** contient des fiches par modèle, millésime et variante, avec leurs équipements.\n\n"
                    "La **couverture** des années, variantes et champs est **partielle**. Une moto fictive reste hors du catalogue réel.\n\n"
                    "Le premier millésime présent ne prouve pas la **date de lancement**. Les détails d’un marché ou d’une version doivent être confirmés par la source."
                )
            with gr.Accordion("Confidentialité et fonctionnement", open=False, elem_classes="bf-guide"):
                if BACKEND == "ollama":
                    if CATALOG_EXPERIMENT_ENABLED:
                        gr.Markdown(
                            "**Parcours expérimental Gold Wing / BMW RT** : recherche dans le catalogue et les publications constructeur conservées localement, "
                            "puis rédaction sur votre machine. Les informations sont accompagnées de leurs sources.\n\n"
                            "**Jev** est le seul service distant : la question, les passages nécessaires et les phrases proposées lui sont transmis pour vérification. "
                            "Les preuves insuffisantes sont signalées.\n\n"
                            "Objectif : moins de dix secondes après le démarrage du service. Ce délai reste à valider, et ne constitue pas une garantie."
                        )
                    elif CATALOG_RESEARCH_ENABLED:
                        gr.Markdown(
                            "**Recherche locale** : Mistral choisit les recherches dans les fiches et rédige à partir des passages retrouvés. "
                            "Les noms, variantes et années sont vérifiés dans le catalogue local.\n\n"
                            "**Jev** est le seul service distant : il contrôle les preuves et les phrases proposées. "
                            "La question et les extraits nécessaires lui sont transmis. Une vérification insuffisante conserve les faits sources et signale les manques.\n\n"
                            "Les recherches peuvent prendre plus d’une minute. Aucune clé à saisir ici."
                        )
                    elif os.getenv("BIKEFINDER_JEV_ROUTER") == "1":
                        gr.Markdown(
                            "**Mode rapide** : Jev comprend la demande, puis le catalogue local fournit les réponses factuelles. "
                            "Les questions et, pour vérifier une synthèse, les extraits nécessaires sont transmis au service distant Jev.\n\n"
                            f"**POC local** : `{OLLAMA_MODEL}` sert aux synthèses nécessaires. Budget de génération : "
                            f'{float(os.getenv("CATALOG_SYNTHESIS_TIMEOUT_SECONDS", "30")):g} s, puis affichage des faits sources '
                            "si la synthèse est trop lente ou non vérifiable. Aucune clé à saisir ici."
                        )
                    else:
                        gr.Markdown(
                            f"**POC local** : modèle `{OLLAMA_MODEL}` exécuté avec Ollama, "
                            "sur le catalogue chargé sur votre machine. Aucune clé API nécessaire. "
                            f"Budget de traitement : {OLLAMA_TURN_TIMEOUT_SECONDS:g} s par question ; "
                            "une recherche déjà en cours peut prolonger l'attente."
                        )
                    api_key_input = gr.Textbox(visible=False)
                else:
                    gr.Markdown(
                        "Cette configuration utilise votre clé [Anthropic](https://console.anthropic.com/) "
                        "ou [OpenRouter](https://openrouter.ai/keys), uniquement pour cette session. "
                        "Les questions et les fiches retenues sont transmises à ce fournisseur."
                    )
                    api_key_input = gr.Textbox(
                        label="Clé API (Anthropic ou OpenRouter)",
                        type="password",
                        placeholder="sk-ant-… ou sk-or-…",
                    )
            gr.Markdown(("Pour explorer : indiquez la famille. Pour une fiche précise : ajoutez l’année et la variante."
                         if CATALOG_RESEARCH_ENABLED else "Modèle + année + variante : trois détails qui rendent la réponse plus précise."),
                        elem_id="bf-footnote")

    chat_event = gr.on(
        triggers=[msg.submit, send.click],
        fn=chat,
        inputs=[msg, chatbot, api_key_input, agent_state],
        outputs=[chatbot, agent_state],
        api_name="chat",
        concurrency_limit=8,
        trigger_mode="once",
        show_progress="minimal",
        show_progress_on=chatbot,
    )
    clear_draft_event = chat_event.then(lambda: "", None, msg, api_visibility="private")
    gr.on(
        triggers=[reset.click, chatbot.clear],
        fn=clear_conversation,
        outputs=[chatbot, agent_state, msg],
        cancels=[chat_event, clear_draft_event],
        queue=False,
        api_visibility="private",
    )


def launch_chatbot(**kwargs):
    """Launch with the presentation settings required by Gradio 6."""
    export_dir = Path(__file__).resolve().parents[2] / "data/technical/chat-exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    kwargs["allowed_paths"] = [*kwargs.get("allowed_paths", []), str(export_dir)]
    options = {
        "server_name": os.environ.get("GRADIO_HOST", "127.0.0.1"),
        "theme": THEME,
        "css": CSS,
        "footer_links": [],
    }
    options.update(kwargs)
    return demo.launch(**options)


if __name__ == "__main__":
    launch_chatbot()
