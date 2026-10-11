// 다크모드 토글 관리
const initDarkMode = () => {
    const darkModeToggle = document.getElementById('darkModeToggle');
    const htmlElement = document.documentElement;

    // ✅ 테마 적용 함수 (재사용 가능하도록)
    const applyTheme = () => {
        const savedTheme = localStorage.getItem('theme') || 'dark';
        htmlElement.setAttribute('data-theme', savedTheme);

        // 버튼 텍스트 업데이트
        if (darkModeToggle) {
            darkModeToggle.title = savedTheme === 'dark' ? '라이트모드로 전환' : '다크모드로 전환';
        }
    };

    // ✅ 초기 테마 적용
    applyTheme();

    // 토글 버튼이 있을 때만 실행
    if (darkModeToggle) {
        // 클릭 이벤트
        darkModeToggle.addEventListener('click', () => {
            const currentTheme = htmlElement.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

            // 테마 변경
            htmlElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);

            // 버튼 텍스트 업데이트
            darkModeToggle.title = newTheme === 'dark' ? '라이트모드로 전환' : '다크모드로 전환';

            if (typeof currentChart !== 'undefined' && currentChart) {
                const titleColor = newTheme === 'dark' ? '#e2e8f0' : '#212529';
                const subtitleColor = newTheme === 'dark' ? '#cbd5e0' : '#495057';
                currentChart.options.plugins.title.color = titleColor;
                currentChart.options.plugins.subtitle.color = subtitleColor;
                currentChart.update();
            }

            // 디버깅용
            console.log('테마 변경됨:', newTheme);
        });
    }
};

// ✅ 페이지 로드 시 실행
document.addEventListener('DOMContentLoaded', initDarkMode);

// ✅ 뒤로가기/앞으로가기 시에도 테마 다시 적용 (bfcache 대응)
window.addEventListener('pageshow', function (event) {
    // bfcache에서 복원된 경우
    if (event.persisted) {
        const savedTheme = localStorage.getItem('theme') || 'dark';
        document.documentElement.setAttribute('data-theme', savedTheme);

        const darkModeToggle = document.getElementById('darkModeToggle');
        if (darkModeToggle) {
            darkModeToggle.title = savedTheme === 'dark' ? '라이트모드로 전환' : '다크모드로 전환';
        }

        console.log('페이지 복원됨, 테마 재적용:', savedTheme);
    }
});