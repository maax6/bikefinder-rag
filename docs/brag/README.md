# Démo vidéo du catalogue technique — octobre 2026

La nouvelle vidéo montre le frontend du chatbot et des réponses réellement
obtenues à partir du catalogue local. Les questions sont ordinaires et les
liens Motoplanète restent visibles dans les tableaux.

Il s'agit d'un **montage de captures d'écran réelles**, avec transitions et
attentes raccourcies. Ce n'est pas un enregistrement continu, une mesure de
latence ni un benchmark général. La vidéo est silencieuse, en français.

Les exemples illustrent les comparaisons de puissance et de poids du même
type, l'intersection de deux équipements de série, et une autonomie estimée
qui conserve sa mention « calculée mais non vérifiée ». Jev interprète les
demandes ; les faits de ces exemples viennent directement du catalogue.
Mistral reste disponible pour les synthèses qui le nécessitent.

Les questions, réponses, routes et empreintes des captures sont consignées
dans `brag-20261013.json`. Les captures proviennent d'un aperçu isolé : le
serveur utilisé par l'utilisateur et la collecte n'ont pas été modifiés pour
la réalisation de la vidéo. Aucune clé API n'est présente dans les assets.

Pour refaire le montage après les captures :

```sh
.venv/bin/python scripts/render_brag_video.py docs/brag/brag-20261013.json
ffprobe -v error -show_entries format=duration,size:stream=width,height,codec_name -of json docs/brag/brag-20261013.mp4
```

Le script nécessite Pillow et FFmpeg. Les assets de septembre (`brag.mp4` et
`brag.jpg`) sont conservés comme historique et ne sont pas utilisés dans le
nouveau montage.
