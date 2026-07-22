# Spring Backend Adapter

```bash
# 버전 확인
./mvnw --version 2>/dev/null || ./gradlew --version
grep "spring-boot" pom.xml build.gradle 2>/dev/null | head -3

# 테스트 레이어 확인
grep -r "@SpringBootTest\|@WebMvcTest\|@DataJpaTest" src/test/ | head -10
```

## Test slice selection — use the narrowest layer

| What | Annotation | Loads |
|---|---|---|
| Controller + HTTP | `@WebMvcTest(MyController.class)` | Web layer only |
| JPA + DB | `@DataJpaTest` | JPA + in-memory DB |
| Service logic | Plain JUnit + Mockito | Nothing Spring |
| Full context | `@SpringBootTest` | Everything — use sparingly |

```java
// WebMvcTest: isolates controller, mocks services
@WebMvcTest(OrderController.class)
class OrderControllerTest {
    @Autowired MockMvc mvc;
    @MockBean OrderService orderService;

    @Test void returns404WhenMissing() throws Exception {
        given(orderService.find(99L)).willThrow(new OrderNotFoundException(99L));
        mvc.perform(get("/orders/99"))
           .andExpect(status().isNotFound())
           .andExpect(jsonPath("$.code").value("ORDER_NOT_FOUND"));
    }
}
```

## Repository and query checks

```java
@DataJpaTest
class OrderRepositoryTest {
    @Autowired OrderRepository repo;
    @Autowired TestEntityManager em;

    @Test void findsByStatus() {
        em.persist(new Order(user, Status.OPEN));
        em.persist(new Order(user, Status.CLOSED));
        assertThat(repo.findByStatus(Status.OPEN)).hasSize(1);
    }
}
```

## Authorization

```java
@Test
@WithMockUser(roles = "USER")
void adminEndpointRejected() throws Exception {
    mvc.perform(delete("/admin/users/1"))
       .andExpect(status().isForbidden());
}
```

## Error response — confirm shape before asserting

```bash
grep -r "ErrorResponse\|ProblemDetail\|@ExceptionHandler" src/main --include="*.java" | head -5
```

## Build commands

```bash
./mvnw test -Dtest=OrderControllerTest      # specific class
./mvnw verify                               # includes integration tests
./gradlew test
./gradlew integrationTest
```

## Common failure paths

1. `SecurityFilterChain` `@Order` wrong → wrong chain matches
2. `spring.main.lazy-initialization=true` in test profile → missing beans hidden at startup
3. OpenAPI schema drift when request/response model changes

---

## Version-specific notes

### Spring Boot 3.x
- Requires Java 17+
- `ProblemDetail` (RFC 7807) available — check if enabled:
  `grep "spring.mvc.problemdetails.enabled" src/main/resources/application*.properties`
- `@MockBean` deprecated in favor of `@MockitoBean` (Spring Boot 3.4+)
- Jakarta EE (not javax) — `jakarta.persistence.*`, `jakarta.validation.*`
- Virtual threads (JDK 21): `spring.threads.virtual.enabled=true` — `ThreadLocal`-based libs may behave differently

### Spring Boot 2.x
- Java 8+ compatible
- Uses `javax.*` packages
- `@MockBean` is standard (not deprecated)
- WebFlux (`WebTestClient`) for reactive; `MockMvc` for servlet
