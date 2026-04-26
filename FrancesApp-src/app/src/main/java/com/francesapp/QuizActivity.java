package com.francesapp;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.os.Handler;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import java.util.Collections;
import java.util.List;

public class QuizActivity extends Activity {

    public static class Question {
        public final String text;
        public final String[] options;
        public final int correctIndex;

        public Question(String text, String[] options, int correctIndex) {
            this.text = text;
            this.options = options;
            this.correctIndex = correctIndex;
        }
    }

    private List<Question> questions;
    private int currentIndex = 0;
    private int score = 0;
    private boolean answered = false;

    private TextView tvProgress, tvQuestion, tvScoreRunning;
    private ProgressBar progressBar;
    private Button[] optionButtons;
    private LinearLayout layoutQuiz, layoutResult;
    private TextView tvResultEmoji, tvResultTitle, tvResultScore, tvResultMessage;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        buildLayout();

        questions = LessonData.getQuizQuestions();
        Collections.shuffle(questions);
        if (questions.size() > 10) {
            questions = questions.subList(0, 10);
        }

        showQuestion();
    }

    private void buildLayout() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#F0F2FF"));

        // Toolbar
        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setOrientation(LinearLayout.HORIZONTAL);
        toolbar.setBackgroundColor(Color.parseColor("#ED2939"));
        toolbar.setPadding(dp(8), dp(8), dp(16), dp(8));
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setMinimumHeight(dp(56));
        toolbar.setElevation(dp(4));

        TextView btnBack = new TextView(this);
        btnBack.setText("‹");
        btnBack.setTextSize(28f);
        btnBack.setTextColor(Color.WHITE);
        btnBack.setGravity(Gravity.CENTER);
        btnBack.setPadding(dp(8), dp(4), dp(12), dp(4));
        btnBack.setOnClickListener(v -> finish());
        toolbar.addView(btnBack);

        TextView tvTitle = new TextView(this);
        tvTitle.setText("Quiz de Francês");
        tvTitle.setTextColor(Color.WHITE);
        tvTitle.setTextSize(18f);
        tvTitle.setTypeface(null, Typeface.BOLD);
        toolbar.addView(tvTitle);

        root.addView(toolbar);

        // === Quiz Layout ===
        layoutQuiz = new LinearLayout(this);
        layoutQuiz.setOrientation(LinearLayout.VERTICAL);
        layoutQuiz.setPadding(dp(16), dp(16), dp(16), dp(16));

        // Progress row
        LinearLayout progressRow = new LinearLayout(this);
        progressRow.setOrientation(LinearLayout.HORIZONTAL);
        progressRow.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout.LayoutParams prp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        prp.bottomMargin = dp(8);
        progressRow.setLayoutParams(prp);

        tvProgress = new TextView(this);
        tvProgress.setTextSize(13f);
        tvProgress.setTextColor(Color.parseColor("#6B7280"));
        tvProgress.setLayoutParams(new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        progressRow.addView(tvProgress);

        tvScoreRunning = new TextView(this);
        tvScoreRunning.setTextSize(13f);
        tvScoreRunning.setTypeface(null, Typeface.BOLD);
        tvScoreRunning.setTextColor(Color.parseColor("#ED2939"));
        progressRow.addView(tvScoreRunning);

        layoutQuiz.addView(progressRow);

        // Progress bar
        progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setProgressDrawable(null);
        progressBar.getIndeterminateDrawable();
        LinearLayout.LayoutParams pbp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(8));
        pbp.bottomMargin = dp(20);
        progressBar.setLayoutParams(pbp);
        layoutQuiz.addView(progressBar);

        // Question card
        LinearLayout questionCard = new LinearLayout(this);
        questionCard.setOrientation(LinearLayout.VERTICAL);
        questionCard.setBackgroundResource(R.drawable.card_bg);
        questionCard.setElevation(dp(4));
        questionCard.setPadding(dp(20), dp(20), dp(20), dp(20));
        LinearLayout.LayoutParams qcp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        qcp.bottomMargin = dp(20);
        questionCard.setLayoutParams(qcp);

        tvQuestion = new TextView(this);
        tvQuestion.setTextSize(18f);
        tvQuestion.setTypeface(null, Typeface.BOLD);
        tvQuestion.setTextColor(Color.parseColor("#1A1A2E"));
        tvQuestion.setGravity(Gravity.CENTER);
        tvQuestion.setLineSpacing(4f, 1f);
        questionCard.addView(tvQuestion);

        layoutQuiz.addView(questionCard);

        // Option buttons
        optionButtons = new Button[4];
        for (int i = 0; i < 4; i++) {
            Button btn = new Button(this);
            btn.setAllCaps(false);
            btn.setTextSize(15f);
            btn.setTextColor(Color.parseColor("#1A1A2E"));
            btn.setBackgroundResource(R.drawable.btn_option_normal);
            btn.setPadding(dp(14), dp(14), dp(14), dp(14));
            LinearLayout.LayoutParams bp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            bp.bottomMargin = dp(10);
            btn.setLayoutParams(bp);
            final int idx = i;
            btn.setOnClickListener(v -> onOptionSelected(idx));
            optionButtons[i] = btn;
            layoutQuiz.addView(btn);
        }

        root.addView(layoutQuiz);

        // === Result Layout ===
        layoutResult = new LinearLayout(this);
        layoutResult.setOrientation(LinearLayout.VERTICAL);
        layoutResult.setGravity(Gravity.CENTER);
        layoutResult.setPadding(dp(32), dp(32), dp(32), dp(32));
        layoutResult.setVisibility(View.GONE);
        LinearLayout.LayoutParams rlp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        layoutResult.setLayoutParams(rlp);

        tvResultEmoji = new TextView(this);
        tvResultEmoji.setTextSize(72f);
        tvResultEmoji.setGravity(Gravity.CENTER);
        layoutResult.addView(tvResultEmoji);

        tvResultTitle = new TextView(this);
        tvResultTitle.setTextSize(28f);
        tvResultTitle.setTypeface(null, Typeface.BOLD);
        tvResultTitle.setTextColor(Color.parseColor("#1A1A2E"));
        tvResultTitle.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams titleP = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        titleP.topMargin = dp(12);
        tvResultTitle.setLayoutParams(titleP);
        layoutResult.addView(tvResultTitle);

        tvResultScore = new TextView(this);
        tvResultScore.setTextSize(20f);
        tvResultScore.setTypeface(null, Typeface.BOLD);
        tvResultScore.setTextColor(Color.parseColor("#002395"));
        tvResultScore.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams scoreP = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        scoreP.topMargin = dp(8);
        tvResultScore.setLayoutParams(scoreP);
        layoutResult.addView(tvResultScore);

        tvResultMessage = new TextView(this);
        tvResultMessage.setTextSize(15f);
        tvResultMessage.setTextColor(Color.parseColor("#6B7280"));
        tvResultMessage.setGravity(Gravity.CENTER);
        tvResultMessage.setLineSpacing(4f, 1f);
        LinearLayout.LayoutParams msgP = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        msgP.topMargin = dp(12);
        tvResultMessage.setLayoutParams(msgP);
        layoutResult.addView(tvResultMessage);

        // Restart button
        Button btnRestart = new Button(this);
        btnRestart.setText("🔄  Tentar Novamente");
        btnRestart.setAllCaps(false);
        btnRestart.setTextColor(Color.WHITE);
        btnRestart.setTextSize(16f);
        btnRestart.setTypeface(null, Typeface.BOLD);
        btnRestart.setBackgroundColor(Color.parseColor("#ED2939"));
        btnRestart.setPadding(dp(16), dp(14), dp(16), dp(14));
        LinearLayout.LayoutParams rbp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        rbp.topMargin = dp(32);
        btnRestart.setLayoutParams(rbp);
        btnRestart.setOnClickListener(v -> {
            startActivity(new Intent(QuizActivity.this, QuizActivity.class));
            finish();
        });
        layoutResult.addView(btnRestart);

        // Back to home button
        Button btnHome = new Button(this);
        btnHome.setText("🏠  Voltar ao Início");
        btnHome.setAllCaps(false);
        btnHome.setTextColor(Color.WHITE);
        btnHome.setTextSize(16f);
        btnHome.setTypeface(null, Typeface.BOLD);
        btnHome.setBackgroundColor(Color.parseColor("#002395"));
        btnHome.setPadding(dp(16), dp(14), dp(16), dp(14));
        LinearLayout.LayoutParams hbp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        hbp.topMargin = dp(12);
        btnHome.setLayoutParams(hbp);
        btnHome.setOnClickListener(v -> finish());
        layoutResult.addView(btnHome);

        root.addView(layoutResult);

        setContentView(root);
    }

    private void showQuestion() {
        if (currentIndex >= questions.size()) { showResult(); return; }

        answered = false;
        Question q = questions.get(currentIndex);
        int total = questions.size();

        tvProgress.setText("Pergunta " + (currentIndex + 1) + " de " + total);
        progressBar.setMax(total);
        progressBar.setProgress(currentIndex);
        tvQuestion.setText(q.text);
        tvScoreRunning.setText("Pontos: " + score);

        for (int i = 0; i < optionButtons.length; i++) {
            optionButtons[i].setText(q.options[i]);
            optionButtons[i].setEnabled(true);
            optionButtons[i].setBackgroundResource(R.drawable.btn_option_normal);
            optionButtons[i].setTextColor(Color.parseColor("#1A1A2E"));
        }
    }

    private void onOptionSelected(int selectedIndex) {
        if (answered) return;
        answered = true;

        Question q = questions.get(currentIndex);
        boolean correct = selectedIndex == q.correctIndex;
        if (correct) score++;

        optionButtons[selectedIndex].setBackgroundResource(correct
                ? R.drawable.btn_option_correct : R.drawable.btn_option_wrong);
        optionButtons[selectedIndex].setTextColor(Color.WHITE);

        if (!correct) {
            optionButtons[q.correctIndex].setBackgroundResource(R.drawable.btn_option_correct);
            optionButtons[q.correctIndex].setTextColor(Color.WHITE);
        }

        for (Button btn : optionButtons) btn.setEnabled(false);

        new Handler().postDelayed(() -> {
            currentIndex++;
            showQuestion();
        }, 1200);
    }

    private void showResult() {
        layoutQuiz.setVisibility(View.GONE);
        layoutResult.setVisibility(View.VISIBLE);

        int total = questions.size();
        int percent = (score * 100) / total;
        tvResultScore.setText(score + " / " + total + " acertos  (" + percent + "%)");

        if (percent >= 90) {
            tvResultEmoji.setText("🏆");
            tvResultTitle.setText("Incrível!");
            tvResultMessage.setText("Você dominou o básico do francês! Continue estudando assim!");
        } else if (percent >= 70) {
            tvResultEmoji.setText("🎉");
            tvResultTitle.setText("Muito bem!");
            tvResultMessage.setText("Ótimo resultado! Revise as lições para chegar a 100%!");
        } else if (percent >= 50) {
            tvResultEmoji.setText("📚");
            tvResultTitle.setText("Continue assim!");
            tvResultMessage.setText("Você está no caminho certo. Revise as lições e tente novamente!");
        } else {
            tvResultEmoji.setText("💪");
            tvResultTitle.setText("Não desista!");
            tvResultMessage.setText("O francês leva tempo para aprender. Revise as lições e tente de novo!");
        }
    }

    private int dp(int dp) {
        return Math.round(dp * getResources().getDisplayMetrics().density);
    }
}
