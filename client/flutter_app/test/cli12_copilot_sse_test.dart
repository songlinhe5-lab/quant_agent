import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:flutter_app/domain/entities/chat_message.dart';
import 'package:flutter_app/domain/ports/chat_stream_gateway.dart';
import 'package:flutter_app/domain/value_objects/api_result.dart';
import 'package:flutter_app/application/copilot/copilot_service.dart';
import 'package:flutter_app/injection.dart';

// ─── Test Doubles ─────────────────────────────────────────────────────────────

/// Fake ChatStreamGateway that emits pre-configured chunks.
class FakeChatStreamGateway implements ChatStreamGateway {
  FakeChatStreamGateway({
    this.chunks = const [],
    this.suggestions = const [],
    this.shouldFail = false,
  });

  final List<ChatChunk> chunks;
  final List<String> suggestions;
  final bool shouldFail;

  int streamCallCount = 0;
  int cancelCallCount = 0;
  List<ChatMessage>? lastMessages;

  @override
  Stream<ChatChunk> streamChat({
    required List<ChatMessage> messages,
    String? sessionId,
  }) {
    lastMessages = messages;
    streamCallCount++;

    if (shouldFail) {
      return Stream.error('Simulated stream error');
    }

    // Emit chunks with a small delay to simulate streaming
    return Stream.fromIterable(chunks);
  }

  @override
  Future<ApiResult<List<String>>> fetchSuggestions({int limit = 6}) async {
    return ApiResult.success(suggestions);
  }

  @override
  void cancel() {
    cancelCallCount++;
  }
}

void main() {
  // ─── ChatChunk entity ──────────────────────────────────────────────────────

  group('ChatChunk', () {
    test('fromJson parses text_chunk', () {
      final chunk = ChatChunk.fromJson({
        'type': 'text_chunk',
        'content': 'Hello world',
      });
      expect(chunk.isTextChunk, isTrue);
      expect(chunk.content, 'Hello world');
      expect(chunk.isToolStart, isFalse);
      expect(chunk.isToolEnd, isFalse);
      expect(chunk.isError, isFalse);
      expect(chunk.isDone, isFalse);
    });

    test('fromJson parses tool_start', () {
      final chunk = ChatChunk.fromJson({
        'type': 'tool_start',
        'name': 'get_quote',
      });
      expect(chunk.isToolStart, isTrue);
      expect(chunk.name, 'get_quote');
    });

    test('fromJson parses tool_end with result', () {
      final chunk = ChatChunk.fromJson({
        'type': 'tool_end',
        'name': 'get_quote',
        'result': '{"price": 368.4}',
      });
      expect(chunk.isToolEnd, isTrue);
      expect(chunk.name, 'get_quote');
      expect(chunk.result, '{"price": 368.4}');
    });

    test('fromJson parses error', () {
      final chunk = ChatChunk.fromJson({
        'type': 'error',
        'content': 'Something went wrong',
      });
      expect(chunk.isError, isTrue);
      expect(chunk.content, 'Something went wrong');
    });

    test('fromJson parses done', () {
      final chunk = ChatChunk.fromJson({'type': 'done'});
      expect(chunk.isDone, isTrue);
      expect(chunk.content, isNull);
    });

    test('fromJson handles unknown type', () {
      final chunk = ChatChunk.fromJson({'type': 'unknown_type'});
      expect(chunk.type, 'unknown_type');
      expect(chunk.isTextChunk, isFalse);
      expect(chunk.isDone, isFalse);
    });

    test('fromJson handles missing type', () {
      final chunk = ChatChunk.fromJson({});
      expect(chunk.type, 'unknown');
    });
  });

  // ─── ChatMessage entity ───────────────────────────────────────────────────

  group('ChatMessage', () {
    test('isUser / isAssistant', () {
      const user = ChatMessage(role: 'user', content: 'hi');
      const assistant = ChatMessage(role: 'assistant', content: 'hello');
      expect(user.isUser, isTrue);
      expect(user.isAssistant, isFalse);
      expect(assistant.isUser, isFalse);
      expect(assistant.isAssistant, isTrue);
    });

    test('copyWith appends content', () {
      const msg = ChatMessage(role: 'assistant', content: 'Hello');
      final updated = msg.copyWith(content: 'Hello World');
      expect(updated.content, 'Hello World');
      expect(updated.role, 'assistant');
    });

    test('copyWith adds tools', () {
      const msg = ChatMessage(role: 'assistant', content: '');
      final withTool = msg.copyWith(tools: [const ToolCall(name: 'search')]);
      expect(withTool.tools, hasLength(1));
      expect(withTool.tools.first.name, 'search');
      expect(withTool.tools.first.status, 'running');
    });
  });

  // ─── ToolCall entity ──────────────────────────────────────────────────────

  group('ToolCall', () {
    test('default status is running', () {
      const tool = ToolCall(name: 'get_quote');
      expect(tool.status, 'running');
      expect(tool.result, isNull);
    });

    test('equatable props', () {
      const a = ToolCall(name: 'search', status: 'done', result: 'ok');
      const b = ToolCall(name: 'search', status: 'done', result: 'ok');
      expect(a, equals(b));
    });
  });

  // ─── CopilotNotifier ──────────────────────────────────────────────────────

  group('CopilotNotifier', () {
    test('sendMessage appends user + assistant messages and streams', () async {
      final fakeGw = FakeChatStreamGateway(
        chunks: [
          const ChatChunk(type: 'text_chunk', content: 'Hello '),
          const ChatChunk(type: 'text_chunk', content: 'World'),
          const ChatChunk(type: 'done'),
        ],
      );

      final container = ProviderContainer(overrides: [
        chatStreamGatewayProvider.overrideWithValue(fakeGw),
      ]);
      addTearDown(container.dispose);

      final notifier = container.read(copilotProvider.notifier);
      await notifier.sendMessage('Hi');

      // Wait for stream to complete
      await Future<void>.delayed(const Duration(milliseconds: 100));

      final state = container.read(copilotProvider);
      expect(state.messages, hasLength(2)); // user + assistant
      expect(state.messages[0].role, 'user');
      expect(state.messages[0].content, 'Hi');
      expect(state.messages[1].role, 'assistant');
      expect(state.messages[1].content, 'Hello World');
      expect(state.isGenerating, isFalse);
    });

    test('sendMessage handles tool_start and tool_end', () async {
      final fakeGw = FakeChatStreamGateway(
        chunks: [
          const ChatChunk(type: 'tool_start', name: 'get_quote'),
          const ChatChunk(type: 'tool_end', name: 'get_quote', result: '368.4'),
          const ChatChunk(type: 'text_chunk', content: 'Price is 368.4'),
        ],
      );

      final container = ProviderContainer(overrides: [
        chatStreamGatewayProvider.overrideWithValue(fakeGw),
      ]);
      addTearDown(container.dispose);

      final notifier = container.read(copilotProvider.notifier);
      await notifier.sendMessage('What is the price?');
      await Future<void>.delayed(const Duration(milliseconds: 100));

      final state = container.read(copilotProvider);
      final assistant = state.messages[1];
      expect(assistant.tools, hasLength(1));
      expect(assistant.tools[0].name, 'get_quote');
      expect(assistant.tools[0].status, 'done');
      expect(assistant.tools[0].result, '368.4');
      expect(assistant.content, 'Price is 368.4');
    });

    test('sendMessage sets error on stream failure', () async {
      final fakeGw = FakeChatStreamGateway(shouldFail: true);

      final container = ProviderContainer(overrides: [
        chatStreamGatewayProvider.overrideWithValue(fakeGw),
      ]);
      addTearDown(container.dispose);

      final notifier = container.read(copilotProvider.notifier);
      await notifier.sendMessage('Hi');
      await Future<void>.delayed(const Duration(milliseconds: 100));

      final state = container.read(copilotProvider);
      expect(state.isGenerating, isFalse);
      expect(state.error, isNotNull);
    });

    test('cancelGeneration calls gateway cancel', () async {
      final fakeGw = FakeChatStreamGateway(
        chunks: [
          const ChatChunk(type: 'text_chunk', content: 'long response...'),
        ],
      );

      final container = ProviderContainer(overrides: [
        chatStreamGatewayProvider.overrideWithValue(fakeGw),
      ]);
      addTearDown(container.dispose);

      final notifier = container.read(copilotProvider.notifier);
      await notifier.sendMessage('Hi');
      notifier.cancelGeneration();

      expect(fakeGw.cancelCallCount, 1);
      final state = container.read(copilotProvider);
      expect(state.isGenerating, isFalse);
    });

    test('loadSuggestions populates suggestions', () async {
      final fakeGw = FakeChatStreamGateway(
        suggestions: ['Analyze AAPL', 'Market overview'],
      );

      final container = ProviderContainer(overrides: [
        chatStreamGatewayProvider.overrideWithValue(fakeGw),
      ]);
      addTearDown(container.dispose);

      final notifier = container.read(copilotProvider.notifier);
      await notifier.loadSuggestions();

      final state = container.read(copilotProvider);
      expect(state.suggestions, hasLength(2));
      expect(state.suggestions[0], 'Analyze AAPL');
    });

    test('clearConversation resets state', () async {
      final fakeGw = FakeChatStreamGateway(
        chunks: [const ChatChunk(type: 'text_chunk', content: 'Hi')],
      );

      final container = ProviderContainer(overrides: [
        chatStreamGatewayProvider.overrideWithValue(fakeGw),
      ]);
      addTearDown(container.dispose);

      final notifier = container.read(copilotProvider.notifier);
      await notifier.sendMessage('Hello');
      await Future<void>.delayed(const Duration(milliseconds: 100));

      expect(container.read(copilotProvider).messages, isNotEmpty);

      notifier.clearConversation();

      final state = container.read(copilotProvider);
      expect(state.messages, isEmpty);
      expect(state.isGenerating, isFalse);
      expect(state.error, isNull);
      expect(state.suggestions, isEmpty);
    });

    test('sendMessage ignores empty text', () async {
      final fakeGw = FakeChatStreamGateway();

      final container = ProviderContainer(overrides: [
        chatStreamGatewayProvider.overrideWithValue(fakeGw),
      ]);
      addTearDown(container.dispose);

      final notifier = container.read(copilotProvider.notifier);
      await notifier.sendMessage('');
      await notifier.sendMessage('   ');

      expect(fakeGw.streamCallCount, 0);
    });
  });
}
