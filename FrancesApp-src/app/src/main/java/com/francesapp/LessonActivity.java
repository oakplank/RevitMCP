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

public class LessonActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        int lessonId = getIntent().getIntExtra("lesson_id", 1);
        LessonData.Lesson lesson = null;
        for (LessonData.Lesson l : LessonData.getLessons()) {
            if (l.id == lessonId) { lesson = l; break; }
        }
        if (lesson == null) { finish(); return; }

        final LessonData.Lesson finalLesson = lesson;

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#F0F2FF"));

        // Toolbar
        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setOrientation(LinearLayout.HORIZONTAL);
        toolbar.setBackgroundColor(Color.parseColor("#002395"));
        toolbar.setPadding(dp(8), dp(8), dp(16), dp(8));
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setMinimumHeight(dp(56));
        toolbar.setElevation(dp(4));

        TextView btnBack = new TextView(this);
        btnBack.setText("‹");
        btnBack.setTextSize(28f);
        btnBack.setTextColor(Color.WHITE);
        btnBack.setGravity(Gravity.CENTER);
        btnBack.setPadding(dp(8), dp(4), dp(8), dp(4));
        btnBack.setOnClickListener(v -> finish());
        toolbar.addView(btnBack);
        root.addView(toolbar);

        // Lesson header
        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.VERTICAL);
        header.setBackgroundColor(Color.parseColor("#002395"));
        header.setPadding(dp(20), dp(4), dp(20), dp(20));

        TextView tvHeader = new TextView(this);
        tvHeader.setText(lesson.emoji + "  " + lesson.title);
        tvHeader.setTextColor(Color.WHITE);
        tvHeader.setTextSize(24f);
        tvHeader.setTypeface(null, Typeface.BOLD);
        header.addView(tvHeader);

        TextView tvSub = new TextView(this);
        tvSub.setText(lesson.description + "  •  " + lesson.words.size() + " palavras");
        tvSub.setTextColor(Color.parseColor("#CCDDFF"));
        tvSub.setTextSize(13f);
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        sp.topMargin = dp(4);
        tvSub.setLayoutParams(sp);
        header.addView(tvSub);
        root.addView(header);

        // Column hints
        LinearLayout hintsRow = new LinearLayout(this);
        hintsRow.setOrientation(LinearLayout.HORIZONTAL);
        hintsRow.setBackgroundColor(Color.parseColor("#EAEFFF"));
        hintsRow.setPadding(dp(16), dp(10), dp(16), dp(10));
        hintsRow.setGravity(Gravity.CENTER_VERTICAL);
        String[] hints = {"#", "Francês", "Pronúncia", "Português"};
        int[] weights = {0, 0, 0, 0};
        int[] widths = {dp(36), 0, 0, 0};
        float[] wts = {0, 1f, 1f, 1f};
        for (int i = 0; i < hints.length; i++) {
            TextView tv = new TextView(this);
            tv.setText(hints[i]);
            tv.setTextSize(11f);
            tv.setTextColor(Color.parseColor("#6B7280"));
            tv.setTypeface(null, Typeface.BOLD);
            if (i == 0) {
                LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(dp(36), ViewGroup.LayoutParams.WRAP_CONTENT);
                tv.setLayoutParams(p);
            } else {
                LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
                tv.setLayoutParams(p);
            }
            hintsRow.addView(tv);
        }
        root.addView(hintsRow);

        // Word list
        ListView listView = new ListView(this);
        listView.setDivider(null);
        listView.setDividerHeight(0);
        listView.setPadding(dp(12), dp(4), dp(12), dp(16));
        listView.setClipToPadding(false);
        listView.setBackgroundColor(Color.parseColor("#F0F2FF"));
        listView.setAdapter(new WordAdapter(lesson.words));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        root.addView(listView, lp);

        // Quiz button at bottom
        TextView btnQuiz = new TextView(this);
        btnQuiz.setText("🎯  Fazer o Quiz Final");
        btnQuiz.setTextColor(Color.WHITE);
        btnQuiz.setTextSize(15f);
        btnQuiz.setTypeface(null, Typeface.BOLD);
        btnQuiz.setGravity(Gravity.CENTER);
        btnQuiz.setBackgroundColor(Color.parseColor("#ED2939"));
        btnQuiz.setPadding(dp(16), dp(14), dp(16), dp(14));
        LinearLayout.LayoutParams qp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        qp.setMargins(dp(16), 0, dp(16), dp(16));
        btnQuiz.setLayoutParams(qp);
        btnQuiz.setOnClickListener(v -> startActivity(new Intent(this, QuizActivity.class)));
        root.addView(btnQuiz);

        setContentView(root);
    }

    private class WordAdapter extends BaseAdapter {
        private final List<LessonData.Word> words;
        WordAdapter(List<LessonData.Word> words) { this.words = words; }
        @Override public int getCount() { return words.size(); }
        @Override public Object getItem(int pos) { return words.get(pos); }
        @Override public long getItemId(int pos) { return pos; }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            LessonData.Word word = words.get(position);

            LinearLayout row = new LinearLayout(LessonActivity.this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setBackgroundResource(R.drawable.card_bg);
            row.setElevation(dp(2));
            row.setPadding(dp(12), dp(12), dp(12), dp(12));
            row.setGravity(Gravity.CENTER_VERTICAL);
            LinearLayout.LayoutParams rp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            rp.setMargins(dp(4), dp(4), dp(4), dp(6));
            row.setLayoutParams(rp);

            // Number circle
            TextView tvNum = new TextView(LessonActivity.this);
            tvNum.setText(String.valueOf(position + 1));
            tvNum.setTextSize(11f);
            tvNum.setTypeface(null, Typeface.BOLD);
            tvNum.setTextColor(Color.WHITE);
            tvNum.setGravity(Gravity.CENTER);
            tvNum.setBackgroundResource(R.drawable.bg_number_circle);
            LinearLayout.LayoutParams np = new LinearLayout.LayoutParams(dp(28), dp(28));
            np.rightMargin = dp(12);
            tvNum.setLayoutParams(np);
            row.addView(tvNum);

            // French + pronunciation
            LinearLayout left = new LinearLayout(LessonActivity.this);
            left.setOrientation(LinearLayout.VERTICAL);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
            left.setLayoutParams(lp);

            TextView tvFrench = new TextView(LessonActivity.this);
            tvFrench.setText(word.french);
            tvFrench.setTextSize(16f);
            tvFrench.setTypeface(null, Typeface.BOLD);
            tvFrench.setTextColor(Color.parseColor("#002395"));
            left.addView(tvFrench);

            TextView tvPron = new TextView(LessonActivity.this);
            tvPron.setText(word.pronunciation);
            tvPron.setTextSize(11f);
            tvPron.setTextColor(Color.parseColor("#6B7280"));
            tvPron.setTypeface(Typeface.defaultFromStyle(Typeface.ITALIC));
            LinearLayout.LayoutParams pp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            pp.topMargin = dp(2);
            tvPron.setLayoutParams(pp);
            left.addView(tvPron);

            row.addView(left);

            // Portuguese
            TextView tvPortuguese = new TextView(LessonActivity.this);
            tvPortuguese.setText(word.portuguese);
            tvPortuguese.setTextSize(14f);
            tvPortuguese.setTextColor(Color.parseColor("#1A1A2E"));
            tvPortuguese.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
            LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
            tp.leftMargin = dp(8);
            tvPortuguese.setLayoutParams(tp);
            row.addView(tvPortuguese);

            return row;
        }
    }

    private int dp(int dp) {
        return Math.round(dp * getResources().getDisplayMetrics().density);
    }
}
