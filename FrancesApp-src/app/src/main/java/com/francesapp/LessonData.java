package com.francesapp;

import java.util.ArrayList;
import java.util.List;

public class LessonData {

    public static class Word {
        public final String french;
        public final String pronunciation;
        public final String portuguese;

        public Word(String french, String pronunciation, String portuguese) {
            this.french = french;
            this.pronunciation = pronunciation;
            this.portuguese = portuguese;
        }
    }

    public static class Lesson {
        public final int id;
        public final String title;
        public final String description;
        public final String emoji;
        public final List<Word> words;

        public Lesson(int id, String title, String description, String emoji, List<Word> words) {
            this.id = id;
            this.title = title;
            this.description = description;
            this.emoji = emoji;
            this.words = words;
        }
    }

    public static List<Lesson> getLessons() {
        List<Lesson> lessons = new ArrayList<>();

        // Lição 1: Saudações
        List<Word> saudacoes = new ArrayList<>();
        saudacoes.add(new Word("Bonjour", "[bon-JJUR]", "Bom dia / Olá"));
        saudacoes.add(new Word("Bonsoir", "[bon-SUAR]", "Boa noite (ao chegar)"));
        saudacoes.add(new Word("Bonne nuit", "[bon-NUI]", "Boa noite (ao dormir)"));
        saudacoes.add(new Word("Au revoir", "[o-re-VUAR]", "Até logo"));
        saudacoes.add(new Word("Salut", "[sa-LU]", "Oi / Tchau (informal)"));
        saudacoes.add(new Word("Comment ça va?", "[co-MAN sa VA]", "Como vai?"));
        saudacoes.add(new Word("Ça va bien", "[sa VA bien]", "Estou bem"));
        saudacoes.add(new Word("Merci", "[mer-SI]", "Obrigado(a)"));
        saudacoes.add(new Word("De rien", "[de RIEN]", "De nada"));
        saudacoes.add(new Word("S'il vous plaît", "[sil-VU-PLE]", "Por favor"));
        saudacoes.add(new Word("Excusez-moi", "[eks-KU-ze-MUA]", "Com licença / Desculpe"));
        saudacoes.add(new Word("Pardon", "[par-DON]", "Perdão"));
        lessons.add(new Lesson(1, "Saudações", "Como cumprimentar em francês", "👋", saudacoes));

        // Lição 2: Números
        List<Word> numeros = new ArrayList<>();
        numeros.add(new Word("Zéro", "[ZE-ro]", "Zero — 0"));
        numeros.add(new Word("Un / Une", "[AN / UN]", "Um / Uma — 1"));
        numeros.add(new Word("Deux", "[DÖ]", "Dois / Duas — 2"));
        numeros.add(new Word("Trois", "[TRUA]", "Três — 3"));
        numeros.add(new Word("Quatre", "[KATR]", "Quatro — 4"));
        numeros.add(new Word("Cinq", "[SANK]", "Cinco — 5"));
        numeros.add(new Word("Six", "[SIS]", "Seis — 6"));
        numeros.add(new Word("Sept", "[SET]", "Sete — 7"));
        numeros.add(new Word("Huit", "[UIT]", "Oito — 8"));
        numeros.add(new Word("Neuf", "[NÖF]", "Nove — 9"));
        numeros.add(new Word("Dix", "[DIS]", "Dez — 10"));
        numeros.add(new Word("Onze", "[ONZ]", "Onze — 11"));
        numeros.add(new Word("Douze", "[DUZ]", "Doze — 12"));
        numeros.add(new Word("Quinze", "[KANZ]", "Quinze — 15"));
        numeros.add(new Word("Vingt", "[VAN]", "Vinte — 20"));
        numeros.add(new Word("Trente", "[TRANT]", "Trinta — 30"));
        numeros.add(new Word("Cent", "[SAN]", "Cem — 100"));
        numeros.add(new Word("Mille", "[MIL]", "Mil — 1000"));
        lessons.add(new Lesson(2, "Números", "Aprenda a contar em francês", "🔢", numeros));

        // Lição 3: Cores
        List<Word> cores = new ArrayList<>();
        cores.add(new Word("Rouge", "[RUJE]", "Vermelho"));
        cores.add(new Word("Bleu / Bleue", "[BLEU]", "Azul"));
        cores.add(new Word("Vert / Verte", "[VER / VERT]", "Verde"));
        cores.add(new Word("Jaune", "[JON]", "Amarelo"));
        cores.add(new Word("Blanc / Blanche", "[BLAN / BLANSH]", "Branco"));
        cores.add(new Word("Noir / Noire", "[NUAR]", "Preto"));
        cores.add(new Word("Orange", "[o-RANJ]", "Laranja"));
        cores.add(new Word("Violet / Violette", "[vio-LE]", "Roxo / Violeta"));
        cores.add(new Word("Rose", "[ROZ]", "Rosa"));
        cores.add(new Word("Gris / Grise", "[GRI / GRIZ]", "Cinza"));
        cores.add(new Word("Marron", "[ma-RON]", "Marrom"));
        cores.add(new Word("Beige", "[BEJ]", "Bege"));
        lessons.add(new Lesson(3, "Cores", "Aprenda as cores em francês", "🎨", cores));

        // Lição 4: Dias da Semana
        List<Word> dias = new ArrayList<>();
        dias.add(new Word("Lundi", "[LAN-di]", "Segunda-feira"));
        dias.add(new Word("Mardi", "[mar-DI]", "Terça-feira"));
        dias.add(new Word("Mercredi", "[mer-KRE-di]", "Quarta-feira"));
        dias.add(new Word("Jeudi", "[JÖ-di]", "Quinta-feira"));
        dias.add(new Word("Vendredi", "[van-DRE-di]", "Sexta-feira"));
        dias.add(new Word("Samedi", "[sam-DI]", "Sábado"));
        dias.add(new Word("Dimanche", "[di-MANSH]", "Domingo"));
        dias.add(new Word("Aujourd'hui", "[o-JJUR-dui]", "Hoje"));
        dias.add(new Word("Demain", "[de-MAN]", "Amanhã"));
        dias.add(new Word("Hier", "[IER]", "Ontem"));
        dias.add(new Word("Cette semaine", "[set-se-MEN]", "Esta semana"));
        dias.add(new Word("Le week-end", "[le wik-END]", "O fim de semana"));
        lessons.add(new Lesson(4, "Dias da Semana", "Dias, hoje e amanhã", "📅", dias));

        // Lição 5: Frases Essenciais
        List<Word> frases = new ArrayList<>();
        frases.add(new Word("Je m'appelle...", "[je-ma-PEL]", "Meu nome é..."));
        frases.add(new Word("J'ai ... ans", "[JE ... AN]", "Tenho ... anos"));
        frases.add(new Word("Je suis brésilien(ne)", "[je-SUI bré-zi-LIAN]", "Sou brasileiro(a)"));
        frases.add(new Word("Je ne comprends pas", "[je-ne-KOM-pran-PA]", "Não entendo"));
        frases.add(new Word("Parlez-vous portugais?", "[par-LE-VU por-tu-GE]", "Você fala português?"));
        frases.add(new Word("Où est...?", "[u-E]", "Onde está...?"));
        frases.add(new Word("Combien ça coûte?", "[KOM-bien sa KUT]", "Quanto custa?"));
        frases.add(new Word("Je voudrais...", "[je-vu-DRE]", "Eu gostaria de..."));
        frases.add(new Word("L'addition, s'il vous plaît", "[la-di-SION sil-vu-PLE]", "A conta, por favor"));
        frases.add(new Word("Je suis perdu(e)", "[je-SUI per-DU]", "Estou perdido(a)"));
        frases.add(new Word("Pouvez-vous répéter?", "[pu-VE-vu re-PE-TE]", "Pode repetir?"));
        frases.add(new Word("Je parle un peu français", "[je PARL an pö fran-SE]", "Falo um pouco de francês"));
        lessons.add(new Lesson(5, "Frases Essenciais", "Frases úteis para o dia a dia", "💬", frases));

        // Lição 6: Vocabulário do Dia a Dia
        List<Word> vocab = new ArrayList<>();
        vocab.add(new Word("Maison", "[me-ZON]", "Casa"));
        vocab.add(new Word("Famille", "[fa-MIJ]", "Família"));
        vocab.add(new Word("Ami(e)", "[a-MI]", "Amigo(a)"));
        vocab.add(new Word("Travail", "[tra-VAJ]", "Trabalho"));
        vocab.add(new Word("École", "[e-KOL]", "Escola"));
        vocab.add(new Word("Eau", "[O]", "Água"));
        vocab.add(new Word("Pain", "[PAN]", "Pão"));
        vocab.add(new Word("Café", "[ka-FE]", "Café"));
        vocab.add(new Word("Restaurant", "[res-to-RAN]", "Restaurante"));
        vocab.add(new Word("Hôtel", "[o-TEL]", "Hotel"));
        vocab.add(new Word("Voiture", "[vua-TUR]", "Carro"));
        vocab.add(new Word("Argent", "[ar-JAN]", "Dinheiro"));
        vocab.add(new Word("Livre", "[LIVR]", "Livro"));
        vocab.add(new Word("Téléphone", "[te-le-FON]", "Telefone"));
        vocab.add(new Word("Médecin", "[me-de-SAN]", "Médico"));
        vocab.add(new Word("Pharmacie", "[far-ma-SI]", "Farmácia"));
        lessons.add(new Lesson(6, "Vocabulário Cotidiano", "Palavras essenciais do dia a dia", "🏠", vocab));

        return lessons;
    }

    public static List<QuizActivity.Question> getQuizQuestions() {
        List<QuizActivity.Question> questions = new ArrayList<>();

        questions.add(new QuizActivity.Question(
            "O que significa 'Bonjour'?",
            new String[]{"Boa noite", "Bom dia / Olá", "Até logo", "De nada"}, 1));

        questions.add(new QuizActivity.Question(
            "Como se diz 'obrigado' em francês?",
            new String[]{"S'il vous plaît", "De rien", "Merci", "Pardon"}, 2));

        questions.add(new QuizActivity.Question(
            "Como se pronuncia o número '5' em francês?",
            new String[]{"Quatre", "Six", "Sept", "Cinq"}, 3));

        questions.add(new QuizActivity.Question(
            "'Rouge' em português significa:",
            new String[]{"Azul", "Verde", "Vermelho", "Amarelo"}, 2));

        questions.add(new QuizActivity.Question(
            "Como se diz 'quarta-feira' em francês?",
            new String[]{"Mardi", "Jeudi", "Mercredi", "Vendredi"}, 2));

        questions.add(new QuizActivity.Question(
            "O que significa 'Je ne comprends pas'?",
            new String[]{"Não falo francês", "Não entendo", "Não sei", "Não quero"}, 1));

        questions.add(new QuizActivity.Question(
            "'Maison' em português significa:",
            new String[]{"Mesa", "Cadeira", "Casa", "Janela"}, 2));

        questions.add(new QuizActivity.Question(
            "Como se diz 'hoje' em francês?",
            new String[]{"Demain", "Hier", "Maintenant", "Aujourd'hui"}, 3));

        questions.add(new QuizActivity.Question(
            "'Au revoir' significa:",
            new String[]{"Olá", "Bom dia", "Até logo", "Por favor"}, 2));

        questions.add(new QuizActivity.Question(
            "Como se diz 'água' em francês?",
            new String[]{"Pain", "Café", "Vin", "Eau"}, 3));

        questions.add(new QuizActivity.Question(
            "Qual é a tradução de 'Vingt'?",
            new String[]{"Dez", "Quinze", "Vinte", "Trinta"}, 2));

        questions.add(new QuizActivity.Question(
            "O que significa 'Bonne nuit'?",
            new String[]{"Bom dia", "Boa tarde", "Boa noite (ao dormir)", "Até logo"}, 2));

        questions.add(new QuizActivity.Question(
            "Como se diz 'branco' em francês?",
            new String[]{"Noir", "Blanc", "Gris", "Beige"}, 1));

        questions.add(new QuizActivity.Question(
            "'Voiture' significa:",
            new String[]{"Avião", "Trem", "Carro", "Ônibus"}, 2));

        questions.add(new QuizActivity.Question(
            "Como se diz 'domingo' em francês?",
            new String[]{"Samedi", "Vendredi", "Lundi", "Dimanche"}, 3));

        return questions;
    }
}
