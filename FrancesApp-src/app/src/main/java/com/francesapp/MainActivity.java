package com.francesapp;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import java.util.List;

public class MainActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try {
            buildUI();
        } catch (Throwable t) {
            // Mostra o erro real na tela para diagnóstico
            TextView err = new TextView(this);
            err.setText("ERRO: " + t.getClass().getSimpleName() + "\n\n" + t.getMessage() + "\n\nStack:\n" + android.util.Log.getStackTraceString(t));
            err.setTextSize(11f);
            err.setPadding(16, 32, 16, 16);
            err.setBackgroundColor(Color.WHITE);
            err.setTextColor(Color.RED);
            setContentView(err);
        }
    }

    private void buildUI() {
        List<LessonData.Lesson> lessons = LessonData.getLessons();

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#F0F2FF"));

        // Header
        root.addView(buildHeader());

        // Label
        TextView label = new TextView(this);
        label.setText("LIÇÕES");
        label.setTextColor(Color.parseColor("#6B7280"));
        label.setTextSize(11f);
        label.setTypeface(null, Typeface.BOLD);
        label.setLetterSpacing(0.15f);
        label.setPadding(dp(16), dp(16), dp(16), dp(8));
        root.addView(label);

        // Lesson list
        ListView listView = new ListView(this);
        listView.setDivider(null);
        listView.setDividerHeight(0);
        listView.setPadding(dp(12), 0, dp(12), dp(8));
        listView.setClipToPadding(false);
        listView.setAdapter(new LessonAdapter(lessons));
        listView.setOnItemClickListener((parent, view, position, id) -> {
            Intent intent = new Intent(MainActivity.this, LessonActivity.class);
            intent.putExtra("lesson_id", lessons.get(position).id);
            startActivity(intent);
        });
        LinearLayout.LayoutParams listParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        root.addView(listView, listParams);

        // Quiz button
        TextView btnQuiz = new TextView(this);
        btnQuiz.setText("🎯  Fazer o Quiz Final");
        btnQuiz.setTextColor(Color.WHITE);
        btnQuiz.setTextSize(16f);
        btnQuiz.setTypeface(null, Typeface.BOLD);
        btnQuiz.setGravity(Gravity.CENTER);
        btnQuiz.setBackgroundColor(Color.parseColor("#ED2939"));
        btnQuiz.setPadding(dp(16), dp(16), dp(16), dp(16));
        int margin = dp(16);
        LinearLayout.LayoutParams quizParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        quizParams.setMargins(margin, 0, margin, margin);
        btnQuiz.setLayoutParams(quizParams);
        btnQuiz.setOnClickListener(v -> startActivity(new Intent(this, QuizActivity.class)));
        root.addView(btnQuiz);

        setContentView(root);
    }

    private View buildHeader() {
        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.VERTICAL);
        header.setBackgroundColor(Color.parseColor("#002395"));
        header.setPadding(dp(24), dp(40), dp(24), dp(24));
        header.setElevation(dp(4));

        TextView tvFlag = new TextView(this);
        tvFlag.setText("🇫🇷");
        tvFlag.setTextSize(48f);
        header.addView(tvFlag);

        TextView tvTitle = new TextView(this);
        tvTitle.setText("Aprenda Francês");
        tvTitle.setTextColor(Color.WHITE);
        tvTitle.setTextSize(28f);
        tvTitle.setTypeface(null, Typeface.BOLD);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        p.topMargin = dp(8);
        tvTitle.setLayoutParams(p);
        header.addView(tvTitle);

        TextView tvSub = new TextView(this);
        tvSub.setText("Curso para Iniciantes  ·  Português → Francês");
        tvSub.setTextColor(Color.parseColor("#CCDDFF"));
        tvSub.setTextSize(13f);
        LinearLayout.LayoutParams p2 = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        p2.topMargin = dp(4);
        tvSub.setLayoutParams(p2);
        header.addView(tvSub);

        return header;
    }

    private class LessonAdapter extends BaseAdapter {
        private final List<LessonData.Lesson> lessons;

        LessonAdapter(List<LessonData.Lesson> lessons) {
            this.lessons = lessons;
        }

        @Override public int getCount() { return lessons.size(); }
        @Override public Object getItem(int pos) { return lessons.get(pos); }
        @Override public long getItemId(int pos) { return pos; }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            LessonData.Lesson lesson = lessons.get(position);

            LinearLayout card = new LinearLayout(MainActivity.this);
            card.setOrientation(LinearLayout.HORIZONTAL);
            card.setBackgroundResource(R.drawable.card_bg);
            card.setElevation(dp(3));
            card.setPadding(dp(16), dp(16), dp(16), dp(16));
            card.setGravity(Gravity.CENTER_VERTICAL);
            LinearLayout.LayoutParams cardParams = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            cardParams.setMargins(dp(4), dp(4), dp(4), dp(8));
            card.setLayoutParams(cardParams);

            // Emoji bubble
            TextView tvEmoji = new TextView(MainActivity.this);
            tvEmoji.setText(lesson.emoji);
            tvEmoji.setTextSize(28f);
            tvEmoji.setGravity(Gravity.CENTER);
            tvEmoji.setBackgroundResource(R.drawable.bg_emoji_circle);
            LinearLayout.LayoutParams ep = new LinearLayout.LayoutParams(dp(52), dp(52));
            ep.rightMargin = dp(14);
            tvEmoji.setLayoutParams(ep);
            card.addView(tvEmoji);

            // Text
            LinearLayout textBlock = new LinearLayout(MainActivity.this);
            textBlock.setOrientation(LinearLayout.VERTICAL);
            LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
            textBlock.setLayoutParams(tp);

            TextView tvTitle = new TextView(MainActivity.this);
            tvTitle.setText(lesson.title);
            tvTitle.setTextSize(16f);
            tvTitle.setTypeface(null, Typeface.BOLD);
            tvTitle.setTextColor(Color.parseColor("#1A1A2E"));
            textBlock.addView(tvTitle);

            TextView tvDesc = new TextView(MainActivity.this);
            tvDesc.setText(lesson.description);
            tvDesc.setTextSize(13f);
            tvDesc.setTextColor(Color.parseColor("#6B7280"));
            LinearLayout.LayoutParams dp2 = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            dp2.topMargin = dp(2);
            tvDesc.setLayoutParams(dp2);
            textBlock.addView(tvDesc);

            card.addView(textBlock);

            // Count
            TextView tvCount = new TextView(MainActivity.this);
            tvCount.setText(lesson.words.size() + " palavras");
            tvCount.setTextSize(11f);
            tvCount.setTypeface(null, Typeface.BOLD);
            tvCount.setTextColor(Color.parseColor("#002395"));
            tvCount.setBackgroundResource(R.drawable.bg_badge);
            tvCount.setPadding(dp(8), dp(4), dp(8), dp(4));
            LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            cp.leftMargin = dp(8);
            tvCount.setLayoutParams(cp);
            card.addView(tvCount);

            // Arrow
            TextView tvArrow = new TextView(MainActivity.this);
            tvArrow.setText("›");
            tvArrow.setTextSize(22f);
            tvArrow.setTextColor(Color.parseColor("#6B7280"));
            LinearLayout.LayoutParams ap = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            ap.leftMargin = dp(8);
            tvArrow.setLayoutParams(ap);
            card.addView(tvArrow);

            return card;
        }
    }

    private int dp(int dp) {
        float density = getResources().getDisplayMetrics().density;
        return Math.round(dp * density);
    }
}
