# Climate Wrapper

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

난방기와 냉방기를 하나의 스마트한 온도조절기로 통합하는 Home Assistant 커스텀 컴포넌트입니다.

[English](README_EN.md) | 한국어

## 특징

- 🔥 **난방기와 냉방기 통합 제어**: 보일러, 에어컨 등을 하나의 온도조절기로 관리
- 🎯 **선택적 구성**: 난방기만, 냉방기만, 또는 둘 다 설정 가능
- 🌡️ **외부 센서 지원**: 별도의 온도/습도 센서 사용 가능 (선택사항)
- 🔄 **자동 상태 동기화**: 기기의 상태와 자동으로 동기화
- 🕐 **명령 쿨다운**: 불필요한 명령 반복 방지
- 🎮 **수동 제어 감지**: 기기를 직접 조작해도 자동으로 모드 전환
- 🔁 **재시도 로직**: 일시적 오류 발생 시 자동 재시도

## 설치

### HACS를 통한 설치 (권장)

1. HACS > Integrations > 우측 상단 메뉴 > Custom repositories
2. Repository: `https://github.com/yoonpooh/climate-wrapper`
3. Category: `Integration`
4. 추가 후 "Climate Wrapper" 검색하여 설치
5. Home Assistant 재시작

### 수동 설치

1. 이 저장소를 다운로드
2. `custom_components/climate_wrapper` 폴더를 Home Assistant의 `custom_components` 디렉토리에 복사
3. Home Assistant 재시작

## 설정

### UI를 통한 설정

1. Home Assistant > 설정 > 기기 및 서비스
2. "통합 구성요소 추가" 클릭
3. "Climate Wrapper" 검색
4. 설정 진행

### 설정 옵션

| 옵션 | 필수 | 설명 | 기본값 |
|------|------|------|--------|
| 이름 | O | 통합 구성요소 이름 | Climate Wrapper |
| 난방기 Entity | X | 난방 기기 (climate 도메인) | - |
| 냉방기 Entity | X | 냉방 기기 (climate 도메인) | - |
| 온도 센서 | X | 외부 온도 센서 | - |
| 습도 센서 | X | 외부 습도 센서 | - |
| 명령 쿨다운 | O | 명령 반복 방지 시간 (초) | 120 |
| 업데이트 주기 | O | 상태 업데이트 주기 (초) | 30 |

**주의**: 난방기 또는 냉방기 중 최소 하나는 필수입니다.

## 사용 예시

### 예시 1: 보일러 + 에어컨

- **난방기**: 스마트 보일러 온도조절기
- **냉방기**: 스마트 에어컨
- **온도 센서**: 거실 온도 센서

→ 거실 온도에 따라 보일러 또는 에어컨을 자동으로 제어

### 예시 2: 에어컨만

- **냉방기**: 스마트 에어컨
- **온도 센서**: 없음 (에어컨 내장 센서 사용)

→ 냉방 전용 온도조절기로 사용

### 예시 3: 전기 히터만

- **난방기**: 스마트 전기 히터
- **온도 센서**: 방 온도 센서

→ 난방 전용 온도조절기로 사용

## 작동 방식

### HVAC 모드

- **OFF**: 모든 기기 꺼짐
- **HEAT**: 난방 모드 (난방기 ON, 냉방기 OFF)
- **COOL**: 냉방 모드 (냉방기 ON, 난방기 OFF)

### 온도 센서

- 외부 온도 센서가 설정된 경우: 해당 센서의 온도 사용
- 외부 온도 센서가 없는 경우: 기기의 `current_temperature` 속성 사용
- 난방기와 냉방기가 모두 있는 경우: 두 기기의 온도 평균값 사용

### 명령 쿨다운

동일한 명령을 쿨다운 시간 내에 반복 전송하지 않습니다:
- HVAC 모드 변경
- 온도 설정 변경

일시적 오류 발생 시 자동으로 재시도합니다.

### 수동 제어 감지

통합 구성요소가 OFF 상태일 때 기기를 직접 켜면:
- 자동으로 해당 모드로 전환 (HEAT 또는 COOL)
- 기기의 목표 온도를 자동으로 채택

## 문제 해결

### 기기가 켜지지 않아요

1. 기기가 `climate.turn_on` 서비스를 지원하는지 확인
2. 로그에서 오류 메시지 확인
3. 쿨다운 시간 경과 후 다시 시도

### 온도가 동기화되지 않아요

1. 기기가 `set_temperature` 서비스를 지원하는지 확인
2. 쿨다운 시간을 줄여보세요 (최소 30초)
3. 기기가 온라인 상태인지 확인

### 모드 전환이 느려요

- 이는 정상입니다. 명령 쿨다운 때문에 의도적으로 지연됩니다
- 쿨다운 시간을 줄이면 더 빠르게 전환되지만, 기기에 부담이 될 수 있습니다

## 기여

이슈와 풀 리퀘스트는 언제나 환영합니다!

## 라이선스

MIT License

## 크레딧

이 프로젝트는 [homeassistant-auto-climate](https://github.com/yoonpooh/homeassistant-auto-climate)을 기반으로 개선되었습니다.

---

[releases-shield]: https://img.shields.io/github/release/yoonpooh/climate-wrapper.svg?style=for-the-badge
[releases]: https://github.com/yoonpooh/climate-wrapper/releases
[license-shield]: https://img.shields.io/github/license/yoonpooh/climate-wrapper.svg?style=for-the-badge
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
