"""Gradio UI for the local proof of concept, using Ollama by default.

Optional Anthropic/OpenRouter backends use a visitor-provided API key.
"""

import os
import re
import unicodedata

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


CATALOG_RESEARCH_ENABLED = BACKEND == "ollama" and os.getenv("BIKEFINDER_CATALOG_RESEARCH") == "1"


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


with gr.Blocks(title="Bikefinder — catalogue technique") as demo:
    gr.Markdown(
        ("# 🏍️ Bikefinder — catalogue technique\n"
         "Explorez une famille de motos sans année imposée. Pour une fiche précise, "
         "indiquez le millésime et la variante. Les réponses présentent les sources et les preuves manquantes.")
        if CATALOG_RESEARCH_ENABLED else
        ("# 🏍️ Bikefinder — catalogue technique\n"
         "Consultez une fiche par modèle et **millésime**, ou comparez plusieurs motos "
         "d'une même année. Précisez la marque, le modèle, l'année et, si vous la "
         "connaissez, la variante. Demandez les unités et les sources des caractéristiques.")
    )
    if BACKEND == "ollama":
        if CATALOG_RESEARCH_ENABLED:
            gr.Markdown(
                "**Recherche locale** : Mistral choisit les recherches dans les fiches et rédige à partir des passages retrouvés. "
                "Les noms, variantes et années sont vérifiés dans le catalogue local.\n\n"
                "**Jev** est le seul service distant : il contrôle les preuves et les phrases proposées. "
                "La question et les extraits nécessaires lui sont transmis. Une vérification insuffisante conserve les faits sources et signale les manques.\n\n"
                "Les recherches peuvent prendre plus d’une minute. Aucune clé à saisir ici."
            )
        elif os.getenv('BIKEFINDER_JEV_ROUTER')=='1':
            gr.Markdown('**Mode rapide** : Jev comprend la demande, puis le catalogue local fournit les réponses factuelles. Les questions et, pour vérifier une synthèse, les extraits nécessaires sont transmis au service distant Jev.')
            gr.Markdown(f'**POC local** : `{OLLAMA_MODEL}` sert uniquement aux synthèses nécessaires. Budget de génération : {float(os.getenv("CATALOG_SYNTHESIS_TIMEOUT_SECONDS","30")):g} s, puis affichage des faits sources si la synthèse est trop lente ou non vérifiable. Aucune clé à saisir ici.')
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
            "**POC avec modèle distant** : cette configuration utilise votre clé "
            "[Anthropic](https://console.anthropic.com/) ou "
            "[OpenRouter](https://openrouter.ai/keys), uniquement pour cette session. "
            "Les questions et les fiches retenues sont transmises à ce fournisseur."
        )
        api_key_input = gr.Textbox(
            label="Clé API (Anthropic ou OpenRouter)",
            type="password",
            placeholder="sk-ant-... or sk-or-...",
        )
    gr.Markdown(
        "**Catalogue enrichi Motoplanète** : recherche par millésime et équipements "
        "de série ou en option, avec les fiches sources. Les autonomies conservent "
        "leurs mentions d’estimation. Une moto fictive reste hors du catalogue réel.\n\n"
        "**Limites du catalogue** : la couverture des années, variantes et champs "
        "est partielle. Une donnée absente reste **inconnue**, y compris pour un "
        "équipement. Le poids sec et le poids tous pleins ne sont pas encore "
        "normalisés séparément : leur comparaison doit rester prudente. "
        "Le premier millésime présent ne prouve pas la date de lancement."
    )
    chatbot = gr.Chatbot(label="Questions techniques")
    msg = gr.Textbox(
        label="Votre question",
        placeholder=("Une moto ou une famille, votre question…" if CATALOG_RESEARCH_ENABLED
                     else "Fiche technique de la Suzuki GSF 1200 N Bandit de 2000 : puissance, couple, poids et sources ?"),
    )
    question_examples = gr.Examples(
        examples=[
            ["Quelles motos ont l'ABS en 2000 ?"],
            ["Quelle est l'autonomie de la BMW R 1150 GS de 2000 ?"],
            ["Donne l'ABS et l'autonomie de la CFMoto 800 MT Explore de 2025, avec la source."],
            ["Donne la fiche technique de la Suzuki GSF 1200 N Bandit de 2000, avec les unités, les sources et les données inconnues."],
            ["Compare la Suzuki GSF 1200 N Bandit et la Kawasaki ER-5 Twister de 2000 dans un tableau : cylindrée, puissance, couple et poids, avec les sources et les données inconnues."],
        ],
        inputs=msg,
        label="Exemples de questions techniques",
    )
    agent_state = gr.State([])

    msg.submit(
        chat,
        inputs=[msg, chatbot, api_key_input, agent_state],
        outputs=[chatbot, agent_state],
        concurrency_limit=8,
    ).then(lambda: "", None, msg)


if __name__ == "__main__":
    demo.launch(server_name=os.environ.get("GRADIO_HOST", "127.0.0.1"))
