-- 애플리케이션 전용 역할. 슈퍼유저가 아니므로 행 수준 보안(RLS)이 적용된다.
-- 마이그레이션은 소유자(pm_owner)로, API 는 pm_app 으로 접속한다.
CREATE ROLE pm_app LOGIN PASSWORD 'pm_app';
CREATE EXTENSION IF NOT EXISTS vector;
