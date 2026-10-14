# Échecs restants après la deuxième passe SQL + RAG

Les deux passes restent des observations historiques : [passe 1](../eval_results/technical/sql-rag-cheap-models-20261014/pilot-v2.json), [passe 2](../eval_results/technical/sql-rag-cheap-models-20261014/pilot-v3.json), leurs relectures [P1](../eval_results/technical/sql-rag-cheap-models-20261014/semantic-review.json) et [P2](../eval_results/technical/sql-rag-cheap-models-20261014/semantic-review-v3.json), ainsi que le [benchmark HTML](../eval_results/technical/sql-rag-cheap-models-20261014/benchmark.html), ne sont pas modifiés par ces corrections. Il n'y a pas de troisième passe ni de nouveau score mesuré.

## Ce que montrent les traces

La deuxième passe finalise 46 des 67 tours exécutés. Les 21 blocages se répartissent en 7 HTTP 429, 4 dépassements de délai, 7 rejets de références et 3 erreurs de schéma. Cinq tours suivants ne sont pas exécutés après un échec, soit 26 échecs sur les 72 tours attendus. Parmi les réponses finalisées, la relecture distingue 36 correctes, 4 partielles et 6 incorrectes.

Les cinq cas dont le score baisse sont précisément Gemma 26B Q01/Q10/Q17 (HTTP 429), Gemini Flash Q10 (délai) et Qwen Q01 (mauvaises associations entre modèles et identifiants). Les erreurs de disponibilité du fournisseur ne prouvent pas une dégradation des outils.

### Luna Q37 : un périmètre réduit sans erreur

Au deuxième tour, Luna obtient d'abord un compte de **3**, sur les huit identifiants corrects. Pour demander les mesures, il recopie ensuite l'identifiant de la MT-10 `d51c2336299ebb74` en `d51c233da84e1c0f`, inexistant. C'est le seul identifiant inconnu observé dans les appels de cette passe.

L'ancien service retourne néanmoins `ok`, `exhaustive=true`, sept fiches examinées et deux correspondances. Luna explique à tort cette différence par une hauteur inconnue ; le compte initial excluait déjà cette inconnue. Le défaut du service consiste à accepter silencieusement un périmètre incomplet. La nouvelle validation rejette les identifiants de périmètre inexistants avant de produire un compte ou une sélection ; elle demande de reprendre les identifiants exacts, sans deviner leur remplacement.

### Preuves visibles mais difficiles à citer

Haiku Q24 cite `c0a73ac3d40825ff:row:12`, ligne réellement livrée dans les passages de la décision d'équipement, mais absente du registre des preuves directement citables. Flash-Lite Q37 cite quatre références `:identity` de fiches dont l'identité et la source sont livrées par `query_catalog`, sans preuve d'identité correspondante. L'exposition des lignes emboîtées et des preuves d'identité corrige cette incohérence. Les preuves d'identité sont explicitement limitées à l'identité ; elles ne prouvent ni une mesure ni un équipement.

Les cinq autres rejets de références concernent des `object_id` nus : Nemotron Q01/Q24/Q27, Qwen Q27 et Flash-Lite Q27. Ils ne deviennent pas automatiquement des preuves. La session peut demander une seule réparation de cette confusion de type, dans les plafonds existants, à partir des preuves déjà reçues ; une référence inconnue reste rejetée.

### Recherche de famille et contexte partiel

La recherche Gold Wing de Haiku Q27 examinait 65 fiches, dont une Triumph `900 Street Twin Gold Line` (`2eb790a5ef2f07ec`). Une correspondance compacte traversait les frontières de mots. Le premier millésime 2018 était juste, mais le périmètre annoncé était faux. Le filtrage lexical corrigé retrouve les 64 fiches Honda de la famille, sans cette Triumph.

Qwen Q37 demande toutes les mesures : le résultat brut de 52 878 caractères est réduit à 23 881, avec un total annoncé de huit et seulement sept lignes livrées. Le marqueur de contexte partiel existe, mais Qwen l'ignore, puis ne lance aucune recherche au deuxième tour. La nouvelle vue conserve les huit lignes, leurs seize preuves d'équipement et un `page_scope` réutilisable, en 23 417 caractères. Elle retire explicitement quatre colonnes secondaires : autonomie, prix, cylindrée et poids tous pleins faits. Les champs des critères et du tri ainsi que les preuves protégées restent intacts. Une colonne omise demeure indisponible dans cette vue et doit être redemandée si la question la nécessite.

L'identité lisible et les preuves supplémentaires occupent davantage de place : la liste simple des huit motos passe de 10 863 à 16 849 caractères, contre 28 873 dans le résultat brut. Le rejeu des 164 résultats enregistrés ne trouve aucune référence cassée et respecte le plafond de 24 000 caractères par résultat (maximum observé : 23 996) ; le plafond cumulé reste 32 000. Il produit trois vues partielles, contre une dans les traces P2 : deux résolutions conservent 47 candidats sur 50 et la liste Q37 conserve ses huit identités mais omet les quatre colonnes secondaires. Les omissions restent annoncées. Cette priorité préserve mieux le périmètre ; elle ne garantit pas que le modèle respectera les limites ou répondra mieux.

## Ce qui reste une erreur de réponse ou de fournisseur

Qwen Q01 associe trois modèles aux mauvaises fiches ; Q24 transforme un équipement inconnu en équipement absent ; Q34 invente une provenance « officielle Honda » ; Q37 produit un compte contradictoire de 3 puis 2 et une hauteur erronée. Flash-Lite Q31 cite des preuves d'identité pour des chiffres. Flash-Lite et Gemma 31B Q34 omettent l'indétermination de l'équipement de l'édition manquante. Les données reçues ne soutiennent pas ces affirmations ou omissions.

Les quatre délais sont dominés par le modèle : les outils prennent de 0 à 0,354 seconde. Gemini Flash Q27 n'obtient aucune première réponse cloud. Gemma 31B Q37 reçoit une soumission après le délai, à 38,81 secondes. Une optimisation SQL ne répare pas ces délais. Trois réparations de format sont tentées, dont deux réussies ; Nemotron Q34/Q37 soumet pour la première fois au dernier round un schéma invalide, sans place restante pour le réparer.

## Validation des corrections

Les corrections concernent le service commun, l'exposition des preuves et la réparation bornée. Leur vérification se fait localement, en rejouant les défauts des traces et des cas génériques, avec des réponses simulées ; aucun nouvel appel cloud n'est effectué et le coût API de ces contrôles est nul. L'analyse structurée est dans [post-pass2-failure-analysis.json](../eval_results/technical/sql-rag-cheap-models-20261014/post-pass2-failure-analysis.json).

La validation intégrée est réussie : **126 tests ciblés passent**. La [vérification sur la base](../eval_results/technical/sql-rag-cheap-models-20261014/post-pass2-service-verification.json) revalide les six outils sur les quarante cas et les 105 687 passages de l'index. Le [rejeu des défauts](../eval_results/technical/sql-rag-cheap-models-20261014/post-pass2-regression-checks.json) rejette la faute de copie exacte de Luna sans produire le faux compte de deux, conserve le compte correct de trois et récupère les trois fiches. Il vérifie aussi la famille Gold Wing, les preuves emboîtées, les preuves d'identité et les huit identités Q37. Les rapports enregistrent les empreintes du corpus et des corrections ; le corpus reste inchangé.

Ces contrôles démontrent que les mécanismes défectueux sont corrigés localement. Les réponses des modèles n'ont pas été régénérées : les erreurs de synthèse restent des observations P2 et aucun nouveau taux de réussite de Luna ou des huit modèles n'est mesuré.
