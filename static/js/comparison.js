// 비교 바구니 관리 클래스
class ComparisonBasket {
    constructor() {
        this.basket = this.loadBasket();
        this.slots = { 1: null, 2: null };
        this.init();
    }

    init() {
        this.renderBasket();
        this.setupDragAndDrop();
        this.updateAddButtons();
        this.setupCompareButton();
        this.updateClearButton();
    }

    // localStorage에서 바구니 불러오기
    loadBasket() {
        const saved = localStorage.getItem('comparisonBasket');
        return saved ? JSON.parse(saved) : [];
    }

    // localStorage에 바구니 저장
    saveBasket() {
        localStorage.setItem('comparisonBasket', JSON.stringify(this.basket));
    }

    // 바구니에 카드 추가/제거 (토글 방식)
    addCard(cardData) {
        // 이미 있는지 확인
        const existingIndex = this.basket.findIndex(card => card.spid === cardData.spid);

        if (existingIndex !== -1) {
            // 이미 있으면 제거 (토글)
            this.removeCard(cardData.spid);
            return 'removed';  // 제거되었음을 표시
        }

        // 10개 제한
        if (this.basket.length >= 10) {
            alert('바구니가 가득 찼습니다. (최대 10개)');
            return false;
        }

        // 새로 추가
        this.basket.push(cardData);
        this.saveBasket();
        this.renderBasket();
        this.updateAddButtons();
        this.updateClearButton();
        return true;
    }

    // 바구니에서 카드 제거
    removeCard(spid) {
        this.basket = this.basket.filter(card => card.spid !== spid);

        // 슬롯에 있으면 슬롯에서도 제거
        if (this.slots[1]?.spid === spid) {
            this.clearSlot(1);
        }
        if (this.slots[2]?.spid === spid) {
            this.clearSlot(2);
        }

        this.saveBasket();
        this.renderBasket();
        this.updateAddButtons();
        this.updateClearButton();
    }

    // 바구니 렌더링
    renderBasket() {
        const leftContainer = document.getElementById('basketLeft');
        const rightContainer = document.getElementById('basketRight');
        const countEl = document.getElementById('basketCount');

        countEl.textContent = this.basket.length;
        document.getElementById('comparisonBar').style.display = this.basket.length > 0 ? 'block' : 'none';
        leftContainer.innerHTML = '';
        rightContainer.innerHTML = '';

        this.basket.forEach((card, index) => {
            const cardEl = this.createBasketCard(card);

            // 0~4번은 왼쪽, 5~9번은 오른쪽
            if (index < 5) {
                leftContainer.appendChild(cardEl);
            } else {
                rightContainer.appendChild(cardEl);
            }
        });

        this.updateClearButton();
    }

    // 바구니 카드 HTML 생성
    createBasketCard(card) {
        const div = document.createElement('div');
        div.className = 'basket-card';
        div.draggable = true;
        div.dataset.spid = card.spid;

        div.innerHTML = `
        <img src="${card.image}" class="basket-card-image" alt="${card.name}">
        ${card.seasonImg ? `<img src="${card.seasonImg}" class="basket-season-icon" alt="${card.season}">` : ''}
        <button class="basket-remove" onclick="basket.removeCard('${card.spid}')">&times;</button>
    `;

        // 드래그 이벤트
        div.addEventListener('dragstart', (e) => {
            e.dataTransfer.setData('cardData', JSON.stringify(card));
            div.classList.add('dragging');
        });

        div.addEventListener('dragend', () => {
            div.classList.remove('dragging');
        });

        // 클릭으로 슬롯에 추가
        div.addEventListener('click', (e) => {
            if (e.target.classList.contains('basket-remove')) return;
            this.addToEmptySlot(card);
        });

        return div;
    }

    // 빈 슬롯에 자동 추가
    addToEmptySlot(card) {
        if (!this.slots[1]) {
            this.fillSlot(1, card);
        } else if (!this.slots[2]) {
            this.fillSlot(2, card);
        } else {
            alert('비교 슬롯이 가득 찼습니다. 기존 카드를 제거해주세요.');
        }
    }

    // 슬롯 채우기
    fillSlot(slotNum, card) {
        this.slots[slotNum] = card;
        this.renderSlot(slotNum);
        this.updateCompareButton();
    }

    // 슬롯 비우기
    clearSlot(slotNum) {
        this.slots[slotNum] = null;
        this.renderSlot(slotNum);
        this.updateCompareButton();
    }

    // 슬롯 렌더링
    renderSlot(slotNum) {
        const slotEl = document.getElementById(`slot${slotNum}`);
        const card = this.slots[slotNum];

        if (!card) {
            slotEl.innerHTML = '<span class="slot-placeholder">클릭/드래그</span>';
            slotEl.classList.remove('filled');
            return;
        }

        slotEl.classList.add('filled');
        slotEl.innerHTML = `
        <div class="slot-card">
            <img src="${card.image}" class="slot-card-image" alt="${card.name}">
            ${card.seasonImg ? `<img src="${card.seasonImg}" class="slot-season-icon" alt="${card.season}">` : ''}
            <button class="slot-remove" onclick="basket.slotToBasket(${slotNum})">&times;</button>
        </div>
    `;
    }

    // 바구니 전체 비우기
    clearAllBasket() {
        if (this.basket.length === 0) {
            return;
        }

        if (confirm('비교 바구니에 있는 카드들을 전부 삭제하겠습니까?')) {
            this.basket = [];
            this.clearSlot(1);
            this.clearSlot(2);
            this.saveBasket();
            this.renderBasket();
            this.updateAddButtons();
            this.updateClearButton();
        }
    }

    // 비우기 버튼 상태 업데이트
    updateClearButton() {
        const clearBtn = document.getElementById('clearBasketBtn');
        if (clearBtn) {
            clearBtn.disabled = this.basket.length === 0;
        }
    }


    // 슬롯에서 바구니로 (X 버튼)
    slotToBasket(slotNum) {
        this.clearSlot(slotNum);
    }

    // 드래그 앤 드롭 설정
    setupDragAndDrop() {
        const slots = [document.getElementById('slot1'), document.getElementById('slot2')];

        slots.forEach((slotEl, index) => {
            const slotNum = index + 1;

            slotEl.addEventListener('dragover', (e) => {
                e.preventDefault();
                slotEl.classList.add('drag-over');
            });

            slotEl.addEventListener('dragleave', () => {
                slotEl.classList.remove('drag-over');
            });

            slotEl.addEventListener('drop', (e) => {
                e.preventDefault();
                slotEl.classList.remove('drag-over');

                const cardData = JSON.parse(e.dataTransfer.getData('cardData'));

                // 이미 슬롯에 카드가 있으면 교체
                if (this.slots[slotNum]) {
                    // 다른 슬롯에서 온 경우 위치 교환
                    const otherSlotNum = slotNum === 1 ? 2 : 1;
                    if (this.slots[otherSlotNum]?.spid === cardData.spid) {
                        const temp = this.slots[slotNum];
                        this.fillSlot(slotNum, cardData);
                        this.fillSlot(otherSlotNum, temp);
                        return;
                    }
                }

                this.fillSlot(slotNum, cardData);
            });
        });
    }

    // 비교 버튼 업데이트
    updateCompareButton() {
        const vsBtn = document.getElementById('vsButton');

        if (this.slots[1] && this.slots[2]) {
            vsBtn.textContent = '비교!';
            vsBtn.classList.add('compare-button');
            vsBtn.style.cursor = 'pointer';
        } else {
            vsBtn.textContent = 'VS';
            vsBtn.classList.remove('compare-button');
            vsBtn.style.cursor = 'default';
        }
    }

    // 비교 버튼 클릭 설정
    setupCompareButton() {
        document.getElementById('vsButton').addEventListener('click', () => {
            if (this.slots[1] && this.slots[2]) {
                // 모달 대신 새 페이지로 이동
                const spid1 = this.slots[1].spid;
                const spid2 = this.slots[2].spid;
                window.location.href = `/compare/${spid1}/${spid2}`;
            }
        });
    }


    // + 버튼 상태 업데이트
    updateAddButtons() {
        document.querySelectorAll('.add-to-basket-btn').forEach(btn => {
            const spid = btn.dataset.spid;
            const inBasket = this.basket.find(card => card.spid === spid);

            if (inBasket) {
                btn.classList.add('added');
                btn.innerHTML = `
                <span class="btn-icon">✓</span>
                <span class="btn-text">추가됨</span>
            `;
            } else {
                btn.classList.remove('added');
                btn.innerHTML = `
                <span class="btn-icon">+</span>
                <span class="btn-text">비교</span>
            `;
            }
        });
    }
}

// 전역 인스턴스 생성
let basket;

document.addEventListener('DOMContentLoaded', () => {
    basket = new ComparisonBasket();
});

// 바구니에 추가/제거 함수 (버튼에서 호출)
function addToBasket(btn) {
    const cardData = {
        spid: btn.dataset.spid,
        name: btn.dataset.name,
        season: btn.dataset.season,
        image: btn.dataset.image,
        seasonImg: btn.dataset.seasonImg,
        nation: btn.dataset.nation,
        nationImg: btn.dataset.nationImg
    };

    const result = basket.addCard(cardData);

    if (result === 'removed') {
        // 제거된 경우 - 버튼을 원래 상태로
        btn.classList.remove('added');
        btn.innerHTML = `
            <span class="btn-icon">+</span>
            <span class="btn-text">비교</span>
        `;
    } else if (result === true) {
        // 추가된 경우 - 버튼을 추가됨 상태로
        btn.classList.add('added');
        btn.innerHTML = `
            <span class="btn-icon">✓</span>
            <span class="btn-text">추가됨</span>
        `;
    }
    // result === false인 경우 (바구니 가득참)는 alert만 표시하고 버튼 상태 유지
}