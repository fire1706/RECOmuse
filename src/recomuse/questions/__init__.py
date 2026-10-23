"""Questions guidées : quand le logiciel n'est pas sûr d'un symbole, il le demande au
musicien (extrait de l'image + choix cliquables) au lieu de deviner.

Fichiers du module :
- questions.py : des problèmes du validateur aux questions (tri, regroupement des doutes
                 de même cause, choix proposés et corrections qu'ils impliquent) ;
- images.py    : image d'une question (zone de la page, symboles douteux entourés) ;
- session.py   : déroulement (questions restantes, réponses, annulation de la dernière).

Les réponses passent par le service de corrections (learning/corrections.py) et sont
gardées dans la table question_answers. Les règles apprises (tâche 12) seront consultées
avant de poser une question.
"""

from recomuse.questions.questions import Choice, Question, build_questions
from recomuse.questions.session import QuestionError, QuestionSession

__all__ = ["Choice", "Question", "QuestionError", "QuestionSession", "build_questions"]
