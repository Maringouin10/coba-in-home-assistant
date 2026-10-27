# COBA — Portail scolaire (pedNet) pour Home Assistant

Intégration personnalisée pour le portail scolaire **COBA pedNet**
(ex. `https://portail.i-esmc.qc.ca/pedNet/login.coba`). Elle reproduit ce que fait
un navigateur (connexion, puis lecture des pages Travaux, Courriels et Horaire) —
COBA n'a pas d'API publique.

## Capteurs

| Capteur | Valeur |
|---|---|
| **Ma moyenne** | moyenne (%) de toutes tes évaluations notées (détail par cours en attribut `cours`) |
| **Moyenne de la classe** | moyenne (%) de la classe pour ces mêmes évaluations |
| **Dernier message** | objet du dernier courriel (attributs : expéditeur, aperçu, 10 derniers messages) |
| **Date du dernier message** | date telle qu'affichée dans le portail |
| **Messages non lus** | nombre de courriels non lus |
| **Jour d'horaire** | numéro du jour du cycle (ex. `6` pour « Jour 6 ») |

Les moyennes sont calculées comme dans le workflow n8n d'origine : moyenne simple
des pourcentages (A=95, B=85, C=75 pour les notes en lettres).

## Installation (HACS)

1. HACS → ⋮ → **Dépôts personnalisés** → `https://github.com/Maringouin10/coba-in-home-assistant`, catégorie **Intégration**
2. Télécharger, redémarrer Home Assistant
3. **Paramètres → Appareils et services → Ajouter une intégration → COBA**
4. Saisir l'URL du portail, le code d'usager et le mot de passe (stockés par Home Assistant, jamais dans le dépôt)

Options : intervalle de rafraîchissement (30 min par défaut) et journalisation de
débogage.

## Si une valeur reste vide

Le message non lu, la date du message et le « jour d'horaire » sont détectés par
heuristique (le HTML exact du portail varie). Active **Journalisation de débogage**
dans les options : le HTML des pages (tableau de bord, travaux, courriels) est écrit
dans les journaux de Home Assistant, ce qui permet d'ajuster les expressions dans
`custom_components/coba/api.py` (`_parse_messages`, `_parse_jour`).
