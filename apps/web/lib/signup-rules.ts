/*
  회원가입 입력 검사(2026-10-14). 서버(apps/api/app/auth_schemas.py 의 SignupRequest)와 같은 규칙을
  화면에서 먼저 알려 준다. 최종 판단은 서버가 한다.
*/
const USERNAME = /^[a-z0-9][a-z0-9._-]{3,29}$/;

/** 고쳐야 할 점. 비어 있으면 보낼 수 있다. */
export function signupProblems(username: string, password: string, confirm: string): string[] {
  const name = username.trim().toLowerCase();
  const problems: string[] = [];
  if (!USERNAME.test(name)) problems.push('아이디는 영문 소문자·숫자·. _ - 로 4~30자이고, 영문이나 숫자로 시작해야 합니다.');
  if (password.length < 8) problems.push('비밀번호는 8자 이상이어야 합니다.');
  else if (password.trim().toLowerCase() === name) problems.push('비밀번호는 아이디와 달라야 합니다.');
  else if (new Set(password).size < 4) problems.push('비밀번호에 서로 다른 글자를 4개 이상 넣어 주세요.');
  if (confirm !== password) problems.push('비밀번호 확인이 비밀번호와 다릅니다.');
  return problems;
}
